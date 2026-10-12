from pathlib import Path
from contextlib import contextmanager
import tempfile

from app.models import AnalysisResult


def validate_report_destination(result: AnalysisResult, destination: Path) -> None:
    target = destination.expanduser().resolve()
    for raw in (result.evidence.original_path, result.evidence.working_copy_path):
        protected = Path(raw).expanduser().resolve()
        same_file = target == protected
        if not same_file and target.exists() and protected.exists():
            same_file = target.samefile(protected)
        if same_file:
            raise ValueError(
                "Отчёт не может заменить оригинал или рабочую копию. Выберите другое имя файла."
            )


@contextmanager
def atomic_report_path(result: AnalysisResult, destination: Path):
    """Reserve a fresh sibling file, then publish only a fully written report."""
    validate_report_destination(result, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=".dfi-report-",
        suffix=destination.suffix,
        dir=destination.parent,
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
    try:
        yield temporary
        validate_report_destination(result, destination)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
