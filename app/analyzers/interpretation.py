"""Bounded, source-linked answers. Certainty refers to a proposition, never a file.

These rules do not estimate probabilities or issue an expert opinion. In particular,
reading an editable tag twice is not independent corroboration of a real-world event.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum

from app.analyzers.timeline import _is_date_field, normalize_date
from app.models import AnalysisResult, FileKind, Finding, IntegrityStatus, ToolRunStatus
from app.resources.labels import parameter_label, source_label

RULESET_VERSION = "kz-metadata-1.0"
LEGAL_SOURCE = "https://old.adilet.zan.kz/rus/docs/Z1700000044"


class AnswerStatus(StrEnum):
    FACT = "fact"
    INDICATION = "indication"
    INSUFFICIENT = "insufficient"
    NOT_CHECKED = "not_checked"


STATUS_LABELS = {
    AnswerStatus.FACT: "Установлен факт",
    AnswerStatus.INDICATION: "Есть признак",
    AnswerStatus.INSUFFICIENT: "Данных недостаточно",
    AnswerStatus.NOT_CHECKED: "Проверка не завершена",
}


@dataclass(frozen=True, slots=True)
class Answer:
    rule_id: str
    question: str
    status: AnswerStatus
    answer: str
    observation: str
    limitation: str
    next_step: str
    draft: str
    finding_ids: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "status": self.status.value,
            "finding_ids": list(self.finding_ids),
        }


_METADATA_CATEGORIES = {
    "EXIF",
    "XMP",
    "PDF Info",
    "OOXML Core Properties",
    "OOXML Extended Properties",
    "Image properties",
    "Media metadata",
}
_IMAGE_KINDS = {
    FileKind.JPEG,
    FileKind.PNG,
    FileKind.TIFF,
    FileKind.GIF,
    FileKind.WEBP,
    FileKind.BMP,
}


def _key(finding: Finding) -> str:
    return re.sub(r"[^a-z0-9]", "", finding.name.casefold())


def _ids(findings: list[Finding]) -> tuple[str, ...]:
    return tuple(f.id for f in findings)


def quoted(value, limit: int = 400) -> str:
    """Plain text, bounded for display, explicitly mark abridged values."""
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) > limit:
        return text[:limit] + "… [сокращено; полное значение в источнике]"
    return text


def _recorded(findings: list[Finding]) -> str:
    if not findings:
        return "Подходящие поля в полученных результатах не представлены."
    lines = [
        f"{parameter_label(f.name)}: "
        f"{('да' if f.value else 'нет') if isinstance(f.value, bool) else quoted(f.value)} "
        f"({source_label(f.source)})" for f in findings[:6]
    ]
    if len(findings) > 6:
        lines.append(f"Ещё записей: {len(findings) - 6}. Все источники доступны ниже.")
    return "\n".join(lines)


def working_copy_verified(result: AnalysisResult) -> bool:
    evidence = result.evidence
    return (
        evidence.integrity_status == IntegrityStatus.VERIFIED
        and bool(re.fullmatch(r"[0-9a-fA-F]{64}", evidence.sha256))
        and evidence.sha256.casefold() == evidence.working_copy_sha256.casefold()
    )


class InterpretationBuilder:
    def build(self, result: AnalysisResult) -> list[Answer]:
        metadata = [
            f
            for f in result.findings
            if f.category in _METADATA_CATEGORIES
            and not f.source.startswith("ExifTool/System")
            and f.value not in (None, "", [], {})
            and f.name != "Part present"
        ]
        # No parsed metadata is not evidence that a metadata reader completed.
        readable = any(f.category in _METADATA_CATEGORIES for f in result.findings)
        partial = (
            result.incomplete
            or bool(result.errors)
            or any(r.status != ToolRunStatus.COMPLETED for r in result.tool_runs)
        )
        absence = (
            AnswerStatus.NOT_CHECKED
            if partial or not readable
            else AnswerStatus.INSUFFICIENT
        )
        answers = [self._format(result), self._integrity(result)]

        authors = [
            f
            for f in metadata
            if _key(f)
            in {
                "author",
                "artist",
                "lastmodifiedby",
                "byline",
                "ownername",
            }
            or (_key(f) == "creator" and f.category in {"OOXML Core Properties", "XMP"})
        ]
        answers.append(
            Answer(
                "authorship",
                "Кто создал файл?",
                AnswerStatus.INSUFFICIENT if authors else absence,
                "Имя в свойствах не устанавливает человека, создавшего файл."
                if authors
                else "По полученным результатам установить автора нельзя.",
                _recorded(authors),
                "Имя можно изменить, унаследовать из шаблона или записать от имени учётной записи. "
                "Несколько программ, прочитавших одно поле, не подтверждают личность независимо.",
                "Сопоставить исходные версии, историю хранения, журналы устройства и сведения об учётных записях.",
                "Исследованные метаданные не содержат достаточных оснований для идентификации лица, "
                "фактически создавшего файл. "
                + (
                    "Обнаруженные имена являются значениями редактируемых полей, а не идентификацией лица."
                    if authors
                    else "В полученных результатах сведения, достаточные для идентификации лица, отсутствуют."
                ),
                _ids(authors),
            )
        )

        dates = [f for f in metadata if _is_date_field(f.name)]
        unknown_zone = any(
            not normalize_date(str(f.value)).get("timezone_present") for f in dates
        )
        answers.append(
            Answer(
                "event_time",
                "Когда файл действительно создали?",
                AnswerStatus.INSUFFICIENT if dates else absence,
                "Записанные даты не доказывают фактическое время создания."
                if dates
                else "Данных для установления фактического времени создания недостаточно.",
                _recorded(dates),
                "Даты метаданных могут меняться при сохранении, переносе или ручном редактировании. "
                "Время файловой системы описывает экземпляр файла. Разные поля могут относиться к разным событиям. "
                + (
                    "Не для всех записей указан часовой пояс; их нельзя автоматически считать временем Казахстана или UTC."
                    if unknown_zone
                    else "Даже явно записанный часовой пояс не подтверждает правильность часов устройства."
                ),
                "Запросить исходный носитель, прежние версии и независимые журналы с известным временем и часовым поясом.",
                "Исследованные метаданные не содержат достаточных оснований для установления фактического "
                "времени первоначального создания файла. Даты, приведённые в основаниях, отражают "
                "содержимое полей и требуют сопоставления с независимыми данными.",
                _ids(dates),
            )
        )

        software = [
            f
            for f in metadata
            if _key(f)
            in {
                "software",
                "producer",
                "creatortool",
                "application",
                "encoder",
                "encodingsoftware",
            }
            or (_key(f) == "creator" and f.category == "PDF Info")
        ]
        answers.append(
            Answer(
                "software",
                "Какая программа оставила следы?",
                AnswerStatus.INDICATION if software else absence,
                "В свойствах есть обозначения программ; историю работы они не доказывают."
                if software
                else "Обозначения программ в выбранных полях не получены.",
                _recorded(software),
                "Поле может сохраняться после конвертации или копироваться из другого файла. "
                "Название редактора не доказывает монтаж, конкретное действие или использование именно этой версии.",
                "Сопоставить структуру файла, прежние версии и образцы, полученные предполагаемой программой.",
                "В исследованных метаданных обнаружены обозначения программного обеспечения, "
                "указанные в основаниях. Они могут отражать создание, сохранение или преобразование файла. "
                "Установить конкретные действия пользователя только по этим полям нельзя."
                if software
                else "В полученных результатах обозначения программ в выбранных полях не обнаружены. "
                "Это не исключает обработку файла программным обеспечением.",
                _ids(software),
            )
        )

        if result.evidence.kind == FileKind.DOCX:
            answers.append(self._word_changes(result))
        gps = [f for f in result.findings if f.category == "GPS"]
        if gps or result.evidence.kind in _IMAGE_KINDS:
            coordinates = [
                f
                for f in gps
                if _key(f)
                in {
                    "gpslatitude",
                    "gpslongitude",
                    "gpsposition",
                    "gpscoordinates",
                }
                and f.value not in (None, "", [], {})
            ]
            answers.append(
                Answer(
                    "location",
                    "Можно ли установить место съёмки?",
                    AnswerStatus.INDICATION if coordinates else absence,
                    "Есть записи координат; фактическое место съёмки ещё не установлено."
                    if coordinates
                    else "Координаты в полученных результатах не представлены.",
                    _recorded(gps),
                    "GPS-поля можно изменить. Наличие координат не доказывает присутствие камеры в этой точке; "
                    "неполная пара координат или неизвестная система отсчёта ограничивают интерпретацию.",
                    "Проверить широту, долготу, направления и систему отсчёта; сопоставить изображение с местностью "
                    "и независимыми материалами. Одна GPS-запись недостаточна.",
                    "В метаданных представлены записи координат, перечисленные в основаниях. "
                    "Эти записи сами по себе не устанавливают фактическое место съёмки."
                    if coordinates
                    else "В полученных результатах координаты не представлены. "
                    "Данных для установления места съёмки по метаданным недостаточно.",
                    _ids(gps),
                )
            )

        answers.append(
            Answer(
                "authenticity",
                "Можно ли считать файл подлинным?",
                AnswerStatus.INSUFFICIENT,
                "Метаданные и контрольная сумма не устанавливают подлинность содержания.",
                "Этот анализ описывает представленный экземпляр и доступные технические признаки.",
                "Совпадение хешей подтверждает совпадение проверенных байтов. Оно не подтверждает правдивость "
                "содержимого, законность происхождения или отсутствие изменений до поступления файла.",
                "Уточнить проверяемое обстоятельство: изменение конкретного фрагмента, тождество эталону, "
                "происхождение или действительность подписи. Для каждого вопроса нужны свои материалы и методы.",
                "Одной проверки метаданных и контрольных сумм недостаточно для вывода о подлинности содержания "
                "представленного файла. Требуются конкретизация вопроса "
                "и исследование относящихся к нему материалов.",
            )
        )
        return answers

    @staticmethod
    def _format(result: AnalysisResult) -> Answer:
        facts = [
            f
            for f in result.findings
            if f.category == "Integrity"
            and f.source == "File signature"
            and f.name in {"Signature format", "Extension matches signature"}
        ]
        known = result.evidence.kind != FileKind.BINARY and any(
            f.name == "Signature format"
            and str(f.value).casefold() == result.evidence.kind.value
            for f in facts
        )
        mismatch = any(
            f.name == "Extension matches signature" and f.value is False for f in facts
        )
        answer = (
            f"Признаки формата: {result.evidence.kind.value.upper()}. "
            + (
                "Расширение имени не соответствует содержимому."
                if mismatch
                else "Формат определён по содержимому."
            )
            if known
            else "Формат по имеющимся результатам уверенно не определён."
        )
        return Answer(
            "format",
            "Что это за файл?",
            AnswerStatus.FACT if known else AnswerStatus.NOT_CHECKED,
            answer,
            _recorded(facts),
            "Распознавание заголовка или структуры контейнера не означает, что весь файл исправен. "
            "Несовпадение расширения само по себе не доказывает умышленную маскировку.",
            "Для повреждённого или неизвестного формата проверить структуру профильным анализатором.",
            "В представленном файле выявлены признаки формата "
            + result.evidence.kind.value.upper()
            + ". "
            + (
                "Расширение имени не соответствует распознанному формату. "
                if mismatch
                else ""
            )
            + "Причина выбора расширения и исправность всех структур этой проверкой не устанавливаются."
            if known
            else "Распознать формат по имеющимся результатам не удалось; необходима дополнительная проверка.",
            _ids(facts),
        )

    @staticmethod
    def _integrity(result: AnalysisResult) -> Answer:
        facts = [
            f
            for f in result.findings
            if f.category == "Integrity"
            and f.source == "SHA-256"
            and f.name
            in {"Working copy hash verified", "Original hash unchanged during analysis"}
        ]
        rechecks = [
            f for f in facts if f.name == "Original hash unchanged during analysis"
        ]
        confirmed = (
            working_copy_verified(result)
            and bool(rechecks)
            and all(f.value is True for f in rechecks)
        )
        return Answer(
            "integrity",
            "Сохранились ли байты при проверке?",
            AnswerStatus.FACT if confirmed else AnswerStatus.NOT_CHECKED,
            "Хеш копии совпал с исходным; хеш оригинала при повторной проверке совпал."
            if confirmed
            else "Неизменность байтов за время проверки не подтверждена полностью.",
            _recorded(facts),
            "Сравниваются контрольные суммы в моменты проверок. События между проверками и изменения "
            "до получения файла этим методом не устанавливаются. Ошибка повторного чтения не доказывает изменение.",
            "Сохранить контрольные суммы и сведения о получении материала; при сбое повторить проверку доступного оригинала.",
            "SHA-256 рабочей копии совпадает с SHA-256 оригинала, вычисленным при получении. "
            "При повторном чтении после анализа SHA-256 оригинала совпал с первоначальным значением. "
            "Вывод относится к сравнению байтов в указанные моменты проверок."
            if confirmed
            else "Неизменность оригинала и соответствие рабочей копии не подтверждены полным "
            "набором проверок. До выяснения причин положительный вывод о целостности не формулируется.",
            _ids(facts),
        )

    @staticmethod
    def _word_changes(result: AnalysisResult) -> Answer:
        facts = [
            f
            for f in result.findings
            if f.category == "Word review"
            and f.source == "Built-in OOXML analyzer"
            and f.name in {"Tracked changes count", "Tracked changes"}
        ]
        counts = [
            f.value
            for f in facts
            if f.name == "Tracked changes count"
            and type(f.value) is int
            and f.value >= 0
        ]
        valid = bool(counts) and len(set(counts)) == 1
        count = counts[0] if valid else None
        text = (
            f"В проверенных XML-частях сохранено записей исправлений: {count}."
            if valid
            else "Проверка записей исправлений не завершена."
        )
        return Answer(
            "word_changes",
            "Сохранились ли исправления Word?",
            AnswerStatus.FACT if valid else AnswerStatus.NOT_CHECKED,
            text,
            text,
            "Это записи механизма исправлений Word, а не полная история. Принятые или удалённые правки "
            "могут отсутствовать. Имена и даты внутри записей не доказывают личность и время действий.",
            "Открыть основания, сопоставить фрагменты с предыдущими версиями и журналами хранения.",
            text + " Проверены основной текст, колонтитулы, сноски и концевые сноски, "
            "если соответствующие части присутствовали. По отсутствию записей нельзя исключить редактирование файла."
            if valid
            else text,
            _ids(facts),
        )

    def snapshot(self, result: AnalysisResult) -> dict:
        return {
            "ruleset": RULESET_VERSION,
            "jurisdiction": "KZ",
            "automatic_draft": True,
            "answers": [answer.to_dict() for answer in self.build(result)],
        }


def draft_text(answer: Answer, result: AnalysisResult) -> str:
    """A reviewable draft with identity and evidence, never an Article 40 message."""
    findings = {f.id: f for f in result.findings}
    grounds = [findings[id_] for id_ in answer.finding_ids if id_ in findings]
    lines = [
        "ЗАГОТОВКА ДЛЯ ИССЛЕДОВАТЕЛЬСКОЙ ЧАСТИ — требуется проверка экспертом",
        f"Вопрос: {answer.question}",
        f"Объект: {result.evidence.original_name}",
        f"SHA-256 при получении: {result.evidence.sha256}",
        f"Анализ: {result.analyzed_at}",
        f"Статус: {STATUS_LABELS[answer.status]}",
        answer.draft,
        "Основания:",
    ]
    if grounds:
        lines.extend(
            f"- {f.source}; {f.location or f.category}; {f.name} = {quoted(f.value, 1200)} [id: {f.id}]"
            + (
                " [исключено пользователем из технического отчёта]"
                if not f.include_in_report
                else ""
            )
            for f in grounds
        )
    else:
        lines.append(
            "- Объём исследования и полученные результаты; прямых полей для ответа не представлено."
        )
    lines += [
        f"Пределы вывода: {answer.limitation}",
        f"Что требуется дополнительно: {answer.next_step}",
        f"Правило: {answer.rule_id}; версия: {RULESET_VERSION}.",
        "Эксперт оценивает достаточность исследования для ответа. НПВ по вопросу, выявленное в ходе "
        "исследования, обосновывается в заключении (ст. 39); сообщение до исследования по ст. 40 — "
        "отдельный документ. Эта заготовка не принимает ни одно из этих решений.",
    ]
    if (
        result.incomplete
        or result.errors
        or any(r.status != ToolRunStatus.COMPLETED for r in result.tool_runs)
    ):
        lines.append(
            "Объём ограничен: часть выбранных проверок не завершена. "
            "Локально установленный факт не означает полноты всего исследования."
        )
    return "\n\n".join(lines)
