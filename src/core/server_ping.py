"""Minecraft 服务器列表 Ping 模块。

实现 Server List Ping (SLP) 协议，用于查询 Minecraft 服务器状态，
包括 MOTD、在线人数、延迟(ping)、服务器图标、版本信息等。

协议参考: https://wiki.vg/Server_List_Ping
"""

from __future__ import annotations

import base64
import json
import socket
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_PORT = 25565
TIMEOUT = 5.0
PING_TIMEOUT = 3.0


@dataclass
class MOTDComponent:
    text: str = ""
    color: str = ""
    bold: bool = False
    italic: bool = False
    underlined: bool = False
    strikethrough: bool = False
    obfuscated: bool = False
    extra: list["MOTDComponent"] = field(default_factory=list)

    def to_plain(self) -> str:
        parts = [self.text]
        for e in self.extra:
            parts.append(e.to_plain())
        return "".join(parts)

    @classmethod
    def from_dict(cls, data: dict | str) -> "MOTDComponent":
        if isinstance(data, str):
            return cls(text=data)
        comp = cls(
            text=data.get("text", ""),
            color=data.get("color", ""),
            bold=data.get("bold", False),
            italic=data.get("italic", False),
            underlined=data.get("underlined", False),
            strikethrough=data.get("strikethrough", False),
            obfuscated=data.get("obfuscated", False),
        )
        for extra_data in data.get("extra", []):
            comp.extra.append(cls.from_dict(extra_data))
        return comp


MINECRAFT_COLORS = {
    "0": "#000000", "1": "#0000AA", "2": "#00AA00", "3": "#00AAAA",
    "4": "#AA0000", "5": "#AA00AA", "6": "#FFAA00", "7": "#AAAAAA",
    "8": "#555555", "9": "#5555FF", "a": "#55FF55", "b": "#55FFFF",
    "c": "#FF5555", "d": "#FF55FF", "e": "#FFFF55", "f": "#FFFFFF",
}

MINECRAFT_FORMATTING = {
    "l": "bold",
    "o": "italic",
    "n": "underlined",
    "m": "strikethrough",
    "k": "obfuscated",
    "r": "reset",
}


def parse_legacy_motd(text: str) -> list[tuple[str, dict]]:
    segments: list[tuple[str, dict]] = []
    current_style: dict = {"color": "#FFFFFF"}
    current_text = ""
    i = 0
    while i < len(text):
        if text[i] == "§" and i + 1 < len(text):
            code = text[i + 1].lower()
            if current_text:
                segments.append((current_text, dict(current_style)))
                current_text = ""
            if code in MINECRAFT_COLORS:
                current_style = {"color": MINECRAFT_COLORS[code]}
            elif code in MINECRAFT_FORMATTING:
                fmt = MINECRAFT_FORMATTING[code]
                if fmt == "reset":
                    current_style = {"color": "#FFFFFF"}
                else:
                    current_style[fmt] = True
            i += 2
        else:
            current_text += text[i]
            i += 1
    if current_text:
        segments.append((current_text, dict(current_style)))
    return segments


@dataclass
class ServerStatus:
    host: str = ""
    port: int = DEFAULT_PORT
    online: bool = False
    latency_ms: int = -1
    version_name: str = ""
    protocol_version: int = -1
    players_online: int = 0
    players_max: int = 0
    motd_raw: str = ""
    motd_text: str = ""
    motd_html: str = ""
    favicon_data: Optional[bytes] = None
    favicon_path: Optional[Path] = None
    error: str = ""

    @property
    def players_text(self) -> str:
        if self.online:
            return f"{self.players_online}/{self.players_max}"
        return "???/???"


def _pack_varint(value: int) -> bytes:
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value != 0:
            byte |= 0x80
        result.append(byte)
        if value == 0:
            break
    return bytes(result)


def _unpack_varint(sock: socket.socket) -> int:
    result = 0
    num_read = 0
    while True:
        byte = sock.recv(1)
        if not byte:
            raise ConnectionError("Connection closed while reading VarInt")
        b = byte[0]
        result |= (b & 0x7F) << (7 * num_read)
        num_read += 1
        if num_read > 5:
            raise ValueError("VarInt too big")
        if not (b & 0x80):
            break
    return result


def _read_varint_from_bytes(data: bytes, offset: int = 0) -> tuple[int, int]:
    result = 0
    num_read = 0
    while offset + num_read < len(data):
        b = data[offset + num_read]
        result |= (b & 0x7F) << (7 * num_read)
        num_read += 1
        if num_read > 5:
            raise ValueError("VarInt too big")
        if not (b & 0x80):
            return (result, num_read)
    raise ConnectionError("Ran out of bytes while reading VarInt")


def _pack_string(s: str) -> bytes:
    encoded = s.encode("utf-8")
    return _pack_varint(len(encoded)) + encoded


def _unpack_string(sock: socket.socket, length: int) -> str:
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise ConnectionError("Connection closed while reading string")
        data += chunk
    return data.decode("utf-8")


def _send_packet(sock: socket.socket, packet_id: int, data: bytes = b"") -> None:
    packet = _pack_varint(packet_id) + data
    length = _pack_varint(len(packet))
    sock.sendall(length + packet)


def _recv_packet(sock: socket.socket) -> tuple[int, bytes]:
    length = _unpack_varint(sock)
    if length == 0:
        return (0, b"")
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise ConnectionError("Connection closed while reading packet")
        data += chunk
    packet_id, varint_len = _read_varint_from_bytes(data, 0)
    return (packet_id, data[varint_len:])


def _build_handshake(host: str, port: int, protocol_version: int = 47, next_state: int = 1) -> bytes:
    data = _pack_varint(protocol_version)
    data += _pack_string(host)
    data += struct.pack(">H", port)
    data += _pack_varint(next_state)
    return data


def motd_to_html(motd_text: str) -> str:
    segments = parse_legacy_motd(motd_text)
    html_parts: list[str] = []
    for text, style in segments:
        escaped = (text
                   .replace("&", "&amp;")
                   .replace("<", "&lt;")
                   .replace(">", "&gt;")
                   .replace("\n", "<br>"))
        if not escaped:
            continue
        styles: list[str] = []
        color = style.get("color", "")
        if color:
            styles.append(f"color: {color}")
        if style.get("bold"):
            styles.append("font-weight: bold")
        if style.get("italic"):
            styles.append("font-style: italic")
        if style.get("underlined"):
            styles.append("text-decoration: underline")
        if style.get("strikethrough"):
            styles.append("text-decoration: line-through")
        if styles:
            html_parts.append(f'<span style="{";".join(styles)}">{escaped}</span>')
        else:
            html_parts.append(escaped)
    return "".join(html_parts)


def motd_component_to_html(comp: MOTDComponent) -> str:
    parts: list[str] = []

    def render(c: MOTDComponent, inherited_style: dict):
        style = dict(inherited_style)
        if c.color:
            if c.color.startswith("#"):
                style["color"] = c.color
            elif c.color in MINECRAFT_COLORS.values():
                style["color"] = c.color
            else:
                color_key = None
                for k, v in MINECRAFT_COLORS.items():
                    if v == c.color or k == c.color:
                        color_key = k
                        break
                if color_key:
                    style["color"] = MINECRAFT_COLORS[color_key]
                else:
                    named = {
                        "black": "#000000", "dark_blue": "#0000AA", "dark_green": "#00AA00",
                        "dark_aqua": "#00AAAA", "dark_red": "#AA0000", "dark_purple": "#AA00AA",
                        "gold": "#FFAA00", "gray": "#AAAAAA", "dark_gray": "#555555",
                        "blue": "#5555FF", "green": "#55FF55", "aqua": "#55FFFF",
                        "red": "#FF5555", "light_purple": "#FF55FF", "yellow": "#FFFF55",
                        "white": "#FFFFFF",
                    }
                    style["color"] = named.get(c.color, "#FFFFFF")
        if c.bold:
            style["bold"] = True
        if c.italic:
            style["italic"] = True
        if c.underlined:
            style["underlined"] = True
        if c.strikethrough:
            style["strikethrough"] = True

        text = c.text
        if text:
            escaped = (text
                       .replace("&", "&amp;")
                       .replace("<", "&lt;")
                       .replace(">", "&gt;")
                       .replace("\n", "<br>"))
            css_parts: list[str] = []
            color = style.get("color", "#FFFFFF")
            css_parts.append(f"color: {color}")
            if style.get("bold"):
                css_parts.append("font-weight: bold")
            if style.get("italic"):
                css_parts.append("font-style: italic")
            if style.get("underlined"):
                css_parts.append("text-decoration: underline")
            if style.get("strikethrough"):
                css_parts.append("text-decoration: line-through")
            parts.append(f'<span style="{";".join(css_parts)}">{escaped}</span>')

        for child in c.extra:
            render(child, style)

    render(comp, {"color": "#FFFFFF"})
    return "".join(parts)


def ping_server(
    host: str,
    port: int = DEFAULT_PORT,
    timeout: float = TIMEOUT,
    protocol_version: int = 47,
) -> ServerStatus:
    status = ServerStatus(host=host, port=port)

    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))

        handshake_data = _build_handshake(host, port, protocol_version, next_state=1)
        _send_packet(sock, 0x00, handshake_data)

        _send_packet(sock, 0x00)

        packet_id, packet_data = _recv_packet(sock)
        if packet_id != 0x00:
            raise ValueError(f"Unexpected packet ID: {packet_id}")

        json_len, varint_bytes = _read_varint_from_bytes(packet_data, 0)
        json_str = packet_data[varint_bytes:varint_bytes + json_len].decode("utf-8")
        response = json.loads(json_str)

        ping_start = time.time()
        ping_payload = struct.pack(">Q", int(ping_start * 1000) & 0xFFFFFFFFFFFFFFFF)
        _send_packet(sock, 0x01, ping_payload)
        try:
            sock.settimeout(PING_TIMEOUT)
            pong_id, pong_data = _recv_packet(sock)
            if pong_id == 0x01 and len(pong_data) >= 8:
                ping_end = time.time()
                status.latency_ms = int((ping_end - ping_start) * 1000)
        except (socket.timeout, ConnectionError, struct.error):
            status.latency_ms = int((time.time() - ping_start) * 1000)

        version = response.get("version", {})
        status.version_name = version.get("name", "")
        status.protocol_version = version.get("protocol", -1)

        players = response.get("players", {})
        status.players_online = players.get("online", 0)
        status.players_max = players.get("max", 0)

        description = response.get("description", "")
        if isinstance(description, dict):
            comp = MOTDComponent.from_dict(description)
            status.motd_text = comp.to_plain()
            status.motd_html = motd_component_to_html(comp)
            status.motd_raw = json.dumps(description, ensure_ascii=False)
        elif isinstance(description, str):
            status.motd_text = description
            status.motd_html = motd_to_html(description)
            status.motd_raw = description
        else:
            status.motd_text = ""
            status.motd_html = ""
            status.motd_raw = str(description)

        favicon_b64 = response.get("favicon", "")
        if favicon_b64 and favicon_b64.startswith("data:image/png;base64,"):
            try:
                status.favicon_data = base64.b64decode(
                    favicon_b64[len("data:image/png;base64,"):]
                )
            except Exception:
                status.favicon_data = None

        status.online = True

    except socket.timeout:
        status.error = "连接超时"
        logger.debug("Ping %s:%d 超时", host, port)
    except ConnectionRefusedError:
        status.error = "连接被拒绝"
        logger.debug("Ping %s:%d 连接被拒绝", host, port)
    except socket.gaierror:
        status.error = "无法解析主机名"
        logger.debug("Ping %s:%d DNS解析失败", host, port)
    except Exception as e:
        status.error = str(e)
        logger.debug("Ping %s:%d 失败: %s", host, port, e)
    finally:
        if sock:
            try:
                sock.close()
            except Exception:
                pass

    return status


def save_favicon(favicon_data: bytes, server_key: str, cache_dir: Path) -> Optional[Path]:
    if not favicon_data:
        return None
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        safe_key = "".join(c if c.isalnum() else "_" for c in server_key)[:64]
        path = cache_dir / f"favicon_{safe_key}.png"
        path.write_bytes(favicon_data)
        return path
    except Exception as e:
        logger.debug("保存favicon失败: %s", e)
        return None
