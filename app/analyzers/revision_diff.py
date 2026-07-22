from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops

from app.models import Finding, FindingLevel


class RevisionVisualDiffer:
    """Creates read-only visual comparisons from Poppler-rendered revision pages."""

    def compare(
        self, render_groups: list[dict[str, object]], destination: Path
    ) -> tuple[list[dict[str, object]], list[Finding]]:
        destination.mkdir(parents=True, exist_ok=True)
        comparisons: list[dict[str, object]] = []
        ordered = sorted(render_groups, key=lambda item: int(item.get("revision", 0)))
        for left_group, right_group in zip(ordered, ordered[1:]):
            left_pages = _page_map(left_group)
            right_pages = _page_map(right_group)
            for page_number in sorted(set(left_pages) | set(right_pages)):
                left = left_pages.get(page_number)
                right = right_pages.get(page_number)
                row: dict[str, object] = {
                    "from_revision": int(left_group.get("revision", 0)),
                    "to_revision": int(right_group.get("revision", 0)),
                    "page": page_number,
                    "left_path": str(left) if left else "",
                    "right_path": str(right) if right else "",
                    "diff_path": "",
                    "changed_percent": 100.0,
                }
                if left is None:
                    row["status"] = "page_added"
                elif right is None:
                    row["status"] = "page_removed"
                else:
                    status, percent, diff_path = self._compare_page(
                        left,
                        right,
                        destination,
                        int(left_group.get("revision", 0)),
                        int(right_group.get("revision", 0)),
                        page_number,
                    )
                    row.update(
                        {
                            "status": status,
                            "changed_percent": percent,
                            "diff_path": str(diff_path) if diff_path else "",
                        }
                    )
                comparisons.append(row)
        changed = [item for item in comparisons if item.get("status") != "identical"]
        findings = [
            Finding(
                "PDF revisions",
                "Visually changed revision pages",
                len(changed),
                "Poppler visual comparison",
                FindingLevel.MANUAL_REVIEW if changed else FindingLevel.INFO,
                details=(
                    "Пиксельные различия требуют проверки: они показывают изменение отображения, "
                    "но сами по себе не устанавливают автора или намерение."
                ),
            ),
            Finding(
                "PDF revisions",
                "Visual revision comparison",
                comparisons,
                "Poppler visual comparison",
            ),
        ]
        return comparisons, findings

    @staticmethod
    def _compare_page(
        left_path: Path,
        right_path: Path,
        destination: Path,
        left_revision: int,
        right_revision: int,
        page_number: int,
    ) -> tuple[str, float, Path | None]:
        with Image.open(left_path) as left_image, Image.open(right_path) as right_image:
            left = left_image.convert("RGB")
            right = right_image.convert("RGB")
            width = max(left.width, right.width)
            height = max(left.height, right.height)
            left_canvas = Image.new("RGB", (width, height), "white")
            right_canvas = Image.new("RGB", (width, height), "white")
            left_canvas.paste(left, (0, 0))
            right_canvas.paste(right, (0, 0))
            difference = ImageChops.difference(left_canvas, right_canvas)
            if difference.getbbox() is None:
                return "identical", 0.0, None
            mask = difference.convert("L").point(lambda value: 255 if value > 8 else 0)
            histogram = mask.histogram()
            changed_pixels = sum(histogram[1:])
            total_pixels = max(1, width * height)
            percent = round(changed_pixels * 100 / total_pixels, 4)
            red = Image.new("RGB", (width, height), (235, 74, 74))
            highlighted = Image.composite(red, right_canvas, mask)
            output = destination / (
                f"revision-{left_revision:03d}-to-{right_revision:03d}-"
                f"page-{page_number:03d}.png"
            )
            highlighted.save(output, format="PNG", optimize=True)
            return "changed", percent, output


def _page_map(group: dict[str, object]) -> dict[int, Path]:
    result: dict[int, Path] = {}
    pages = group.get("pages", [])
    if not isinstance(pages, list):
        return result
    for page in pages:
        if not isinstance(page, dict) or not page.get("path"):
            continue
        path = Path(str(page["path"]))
        if path.is_file():
            result[int(page.get("page", len(result) + 1))] = path
    return result
