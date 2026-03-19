from __future__ import annotations

import asyncio
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileIconProvider,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .database import DatabaseManager, FileRecord
from .fragments import Fragmenter
from .telegram_client import TelegramClientManager


class UploadWorker(QObject):
    finished = Signal(bool, str)

    def __init__(self, file_path: Path, db: DatabaseManager, telegram: TelegramClientManager) -> None:
        super().__init__()
        self.file_path = file_path
        self.db = db
        self.telegram = telegram
        self.fragmenter = Fragmenter()

    @Slot()
    def run(self) -> None:
        fragment_paths: list[Path] = []
        try:
            temp_dir = Path(tempfile.gettempdir()) / "telezip_uploads"
            fragments = self.fragmenter.create_fragments(self.file_path, temp_dir)
            fragment_paths = [fragment.zip_path for fragment in fragments]
            message_ids = asyncio.run(self.telegram.send_fragments(fragment_paths))
            self.db.add_record(
                original_path=self.file_path.name,
                original_size=self.file_path.stat().st_size,
                added_at=datetime.utcnow(),
                fragment_names=[fragment.part_name for fragment in fragments],
                message_ids=message_ids,
            )
            self.finished.emit(True, "Файл успешно загружен в Telegram.")
        except Exception as exc:  # pragma: no cover - GUI surface
            self.finished.emit(False, str(exc))
        finally:
            if fragment_paths:
                self.fragmenter.cleanup(fragment_paths)


class DownloadWorker(QObject):
    finished = Signal(bool, str)

    def __init__(self, record: FileRecord, telegram: TelegramClientManager) -> None:
        super().__init__()
        self.record = record
        self.telegram = telegram
        self.fragmenter = Fragmenter()

    @Slot()
    def run(self) -> None:
        fragment_zip_paths: list[Path] = []
        assembled: Path | None = None
        try:
            temp_dir = Path(tempfile.gettempdir()) / "telezip_downloads"
            temp_dir.mkdir(parents=True, exist_ok=True)
            fragment_zip_paths = asyncio.run(
                self.telegram.download_fragments(
                    self.record.fragment_names, self.record.message_ids, temp_dir
                )
            )
            assembled = temp_dir / self.record.original_path
            self.fragmenter.assemble(fragment_zip_paths, assembled)
            downloads_folder = Path.home() / "Downloads"
            downloads_folder.mkdir(parents=True, exist_ok=True)
            destination = downloads_folder / self.record.original_path
            if destination.exists():
                destination.unlink()
            assembled.replace(destination)
            self.finished.emit(True, f"Файл сохранён в {destination}.")
        except Exception as exc:  # pragma: no cover - GUI surface
            self.finished.emit(False, str(exc))
        finally:
            if fragment_zip_paths:
                self.fragmenter.cleanup(fragment_zip_paths)
            if assembled:
                assembled.unlink(missing_ok=True)


class MainWindow(QMainWindow):
    def __init__(self, db: DatabaseManager, telegram: TelegramClientManager) -> None:
        super().__init__()
        self.db = db
        self.telegram = telegram
        self.icon_provider = QFileIconProvider()

        self.setWindowTitle("TeleZip")
        self.resize(900, 600)
        self.setAcceptDrops(True)

        central_widget = QWidget(self)
        layout = QVBoxLayout(central_widget)
        self.setCentralWidget(central_widget)

        info_label = QLabel(
            "Перетащите файл в это окно, чтобы загрузить его в Telegram (Избранное)."
        )
        layout.addWidget(info_label)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([
            "Имя",
            "Дата добавления",
            "Размер",
            "Фрагменты",
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        button_layout = QHBoxLayout()
        self.download_button = QPushButton("Загрузить")
        self.download_button.clicked.connect(self.on_download_clicked)
        button_layout.addWidget(self.download_button)

        self.refresh_button = QPushButton("Обновить")
        self.refresh_button.clicked.connect(self.populate_table)
        button_layout.addWidget(self.refresh_button)

        layout.addLayout(button_layout)

        self.populate_table()

    # Drag-and-drop events
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # pragma: no cover - UI event
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # pragma: no cover - UI event
        urls = event.mimeData().urls()
        if not urls:
            return
        local_path = Path(urls[0].toLocalFile())
        if not local_path.is_file():
            QMessageBox.warning(self, "Ошибка", "Можно перетащить только файлы.")
            return
        self._start_upload(local_path)

    def _start_upload(self, file_path: Path) -> None:
        self.download_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.statusBar().showMessage(f"Загрузка {file_path.name}...")
        self._upload_thread = QThread()
        self._upload_worker = UploadWorker(file_path, self.db, self.telegram)
        self._upload_worker.moveToThread(self._upload_thread)
        self._upload_thread.started.connect(self._upload_worker.run)
        self._upload_worker.finished.connect(self._on_upload_finished)
        self._upload_worker.finished.connect(self._upload_thread.quit)
        self._upload_worker.finished.connect(self._upload_worker.deleteLater)
        self._upload_thread.finished.connect(self._upload_thread.deleteLater)
        self._upload_thread.start()

    def _on_upload_finished(self, success: bool, message: str) -> None:
        self.download_button.setEnabled(True)
        self.refresh_button.setEnabled(True)
        self.statusBar().clearMessage()
        if success:
            self.populate_table()
            QMessageBox.information(self, "Готово", message)
        else:
            QMessageBox.critical(self, "Ошибка", message)

    def populate_table(self) -> None:
        self.table.setRowCount(0)
        for record in self.db.list_records():
            self._add_record_to_table(record)

    def _add_record_to_table(self, record: FileRecord) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        icon = self.icon_provider.icon(QFileIconProvider.File)
        name_item = QTableWidgetItem(icon, record.original_path)
        name_item.setData(Qt.UserRole, record.id)
        self.table.setItem(row, 0, name_item)

        date_item = QTableWidgetItem(record.added_at.strftime("%Y-%m-%d %H:%M:%S"))
        self.table.setItem(row, 1, date_item)

        size_item = QTableWidgetItem(self._format_size(record.original_size))
        self.table.setItem(row, 2, size_item)

        fragments_item = QTableWidgetItem(str(record.fragment_count))
        self.table.setItem(row, 3, fragments_item)

    def _format_size(self, size: int) -> str:
        for unit in ["Б", "КБ", "МБ", "ГБ", "ТБ"]:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} ПБ"

    def on_download_clicked(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Загрузка", "Выберите файл в таблице.")
            return
        item = self.table.item(row, 0)
        record_id = item.data(Qt.UserRole)
        record = self.db.get_record(record_id)
        if not record:
            QMessageBox.warning(self, "Загрузка", "Запись не найдена в базе.")
            return
        self._start_download(record)

    def _start_download(self, record: FileRecord) -> None:
        self.download_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.statusBar().showMessage(f"Скачивание {record.original_path} из Telegram...")
        self._download_thread = QThread()
        self._download_worker = DownloadWorker(record, self.telegram)
        self._download_worker.moveToThread(self._download_thread)
        self._download_thread.started.connect(self._download_worker.run)
        self._download_worker.finished.connect(self._on_download_finished)
        self._download_worker.finished.connect(self._download_thread.quit)
        self._download_worker.finished.connect(self._download_worker.deleteLater)
        self._download_thread.finished.connect(self._download_thread.deleteLater)
        self._download_thread.start()

    def _on_download_finished(self, success: bool, message: str) -> None:
        self.download_button.setEnabled(True)
        self.refresh_button.setEnabled(True)
        self.statusBar().clearMessage()
        if success:
            QMessageBox.information(self, "Готово", message)
        else:
            QMessageBox.critical(self, "Ошибка", message)


def run_app() -> None:
    data_dir = Path.home() / ".telezip"
    db = DatabaseManager(data_dir)

    app = QApplication(sys.argv)
    try:
        telegram = TelegramClientManager(data_dir)
    except RuntimeError as exc:  # pragma: no cover - configuration error
        QMessageBox.critical(None, "TeleZip", str(exc))
        sys.exit(1)
    window = MainWindow(db, telegram)
    window.show()
    sys.exit(app.exec())


__all__ = ["run_app"]

