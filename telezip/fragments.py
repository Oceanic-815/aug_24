from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List
import zipfile

CHUNK_SIZE_BYTES = int(3.9 * 1024**3)  # 3.9 GiB


@dataclass
class Fragment:
    """Metadata describing a generated fragment."""

    zip_path: Path
    part_name: str
    size: int


class Fragmenter:
    """Create and reconstruct zip fragments from large files."""

    def __init__(self, chunk_size: int = CHUNK_SIZE_BYTES) -> None:
        self.chunk_size = chunk_size

    def create_fragments(self, source: Path, destination: Path) -> List[Fragment]:
        """Split *source* into ``.zip`` fragments in *destination*.

        Each fragment contains a single entry with the raw bytes of the
        original file chunk. The generated files are returned in order.
        """

        destination.mkdir(parents=True, exist_ok=True)
        fragments: List[Fragment] = []
        part_index = 1
        with source.open("rb") as stream:
            while True:
                chunk = stream.read(self.chunk_size)
                if not chunk:
                    break
                part_stem = f"{source.name}.part{part_index:03d}"
                zip_path = destination / f"{part_stem}.zip"
                info = zipfile.ZipInfo(filename=part_stem)
                info.date_time = _dt.datetime.now().timetuple()[:6]
                info.external_attr = 0o600 << 16
                with zipfile.ZipFile(
                    zip_path,
                    mode="w",
                    compression=zipfile.ZIP_STORED,
                    allowZip64=True,
                ) as archive:
                    archive.writestr(info, chunk)
                fragments.append(Fragment(zip_path=zip_path, part_name=part_stem, size=len(chunk)))
                part_index += 1
        return fragments

    def assemble(self, fragments: Iterable[Path], output_file: Path) -> None:
        """Combine *fragments* into *output_file* in order."""

        output_file.parent.mkdir(parents=True, exist_ok=True)
        with output_file.open("wb") as destination:
            for fragment_path in fragments:
                with zipfile.ZipFile(fragment_path, mode="r") as archive:
                    names = archive.namelist()
                    if len(names) != 1:
                        raise ValueError(
                            f"Fragment {fragment_path} is expected to contain exactly one entry"
                        )
                    with archive.open(names[0], mode="r") as entry:
                        while True:
                            chunk = entry.read(1024 * 1024)
                            if not chunk:
                                break
                            destination.write(chunk)

    def cleanup(self, fragments: Iterable[Path]) -> None:
        parents: set[Path] = set()
        for fragment_path in fragments:
            parents.add(fragment_path.parent)
            try:
                fragment_path.unlink()
            except FileNotFoundError:
                continue
        for parent in parents:
            try:
                if parent.exists() and not any(parent.iterdir()):
                    parent.rmdir()
            except OSError:
                continue

