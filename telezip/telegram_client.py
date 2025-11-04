from __future__ import annotations

import json
from pathlib import Path
from typing import List, Sequence

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import InputPeerSelf

CONFIG_FILENAME = "config.json"


class TelegramClientManager:
    """Wrapper around Telethon ``TelegramClient`` with simple configuration."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.base_dir / CONFIG_FILENAME
        self.session_path = self.base_dir / "telezip.session"
        self._config = self._load_config()

    def _load_config(self) -> dict:
        if not self.config_path.exists():
            example = {
                "api_id": "your_api_id",
                "api_hash": "your_api_hash",
                "phone": "+10000000000"
            }
            self.config_path.write_text(json.dumps(example, indent=2), encoding="utf-8")
            raise RuntimeError(
                f"Телеграм-конфигурация не найдена. Заполните файл {self.config_path} перед запуском."
            )
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def _create_client(self) -> TelegramClient:
        api_id = int(self._config["api_id"])
        api_hash = self._config["api_hash"]
        return TelegramClient(self.session_path, api_id, api_hash)

    async def _ensure_authorized(self, client: TelegramClient) -> None:
        if await client.is_user_authorized():
            return
        phone = self._config.get("phone")
        if not phone:
            raise RuntimeError("Номер телефона не указан в конфигурации.")
        await client.send_code_request(phone)
        code = input("Введите код подтверждения Telegram: ")
        try:
            await client.sign_in(phone=phone, code=code)
        except SessionPasswordNeededError:
            password = input("Введите пароль двухфакторной аутентификации: ")
            await client.sign_in(password=password)

    async def send_fragments(self, fragment_paths: Sequence[Path]) -> List[int]:
        client = self._create_client()
        await client.connect()
        try:
            await self._ensure_authorized(client)
            message_ids: List[int] = []
            for fragment in fragment_paths:
                message = await client.send_file(InputPeerSelf(), fragment, caption=fragment.name)
                message_ids.append(message.id)
            return message_ids
        finally:
            await client.disconnect()

    async def download_fragments(
        self,
        fragment_names: Sequence[str],
        message_ids: Sequence[int],
        destination: Path,
    ) -> List[Path]:
        client = self._create_client()
        await client.connect()
        try:
            await self._ensure_authorized(client)
            saved_messages = InputPeerSelf()
            downloaded: List[Path] = []
            message_map = {}
            if message_ids:
                fetched = await client.get_messages(saved_messages, ids=list(message_ids))
                message_map = {message.id: message for message in fetched if message}
                if len(message_map) != len(message_ids):
                    message_map = {}

            for idx, name in enumerate(fragment_names):
                message = None
                if message_map:
                    target_id = message_ids[idx]
                    message = message_map.get(target_id)
                if message is None:
                    matches = await client.get_messages(saved_messages, search=name, limit=1)
                    if not matches:
                        raise FileNotFoundError(
                            f"Фрагмент {name} не найден в Избранном Telegram."
                        )
                    message = matches[0]
                if not getattr(message, "file", None):
                    raise RuntimeError(f"Сообщение без вложения для фрагмента {name}.")
                target_name = message.file.name or f"{name}.zip"
                path = await client.download_media(message, file=destination / target_name)
                if path is None:
                    raise RuntimeError(f"Не удалось скачать фрагмент {name}.")
                downloaded.append(Path(path))
            return downloaded
        finally:
            await client.disconnect()

