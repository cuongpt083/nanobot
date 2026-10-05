# Pi Runtime Spike Report (Pi 1.0.2)

Recorded against pinned binary: `1.0.2` on Windows AMD64.

| Giả định | Mô tả | Kết quả | Bằng chứng |
|---|---|---|---|
| H1 | `--no-extensions` không vô hiệu hoá `--extension <path>` | PASS | Found spike_ping in get_commands: True (total commands: 18) |
| H3 | `pi.appendEntry` xuất hiện trong `get_entries` | PASS | Found spike_entry in get_entries: True (entries count: 2) |
| H4 | `pi.setActiveTools` qua extension thay đổi tools active | PASS | Response to /spike_set_tools: {'id': 'h4_cmd', 'type': 'response', 'command': 'prompt', 'success': True, 'data': {'disposition': 'handled'}} |
