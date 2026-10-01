# Implementation plan — Coding agent dùng thư mục dự án của phiên (+ chế độ `direct` cho thư mục không phải git)

- Status: **draft, chưa triển khai** (chưa sửa code). Viết 2026-10-01. Branch: `develop`.
- Liên quan: `docs/coworker/plans/advisor-webui.md` (Coding agent, settings), `.agent/security.md` (workspace scope).
- Commit style: `feat(coworker): …`, `fix(coworker): …`, `feat(webui): …`.

## 1. Mục tiêu

1. Người dùng chọn **project directory** khi tạo phiên chat trên WebUI; coding agent làm việc trên thư mục đó, không
   cần khai báo `coding.repos` trong Settings.
2. Thư mục **không phải git** (viết tài liệu, slide…) vẫn dùng được coding agent qua chế độ `direct`.
3. Giữ nguyên bảo đảm an toàn của allowlist hiện tại: LLM không tự mở rộng được tập thư mục được phép.

Ngoài phạm vi: tự động `git init` ngầm (chỉ khi người dùng yêu cầu rõ — T-P6); ép giới hạn workspace ở tầng backend (xem D13).

## 2. Hiện trạng (đã đọc code)

| Điểm | Vị trí | Ghi chú |
|------|--------|---------|
| Allowlist repo | `coding/workspace.py:74 validate_repo` | Chặn tham số `repo` do LLM tự điền |
| Chọn repo | `coding/runner.py:69-79 admit` | Từ chối nếu `repos` rỗng; nhiều repo mà không chỉ định → lỗi |
| Gọi `validate_repo` | `coding/commands.py:119,149,169`, `runner.admit` | merge / discard / resume |
| Admit không có turn | `room/scheduler.py:257 _run_guest` | Chạy nền, **không có** ContextVar scope |
| Worktree | `workspace.create_worktree`, `merge`, `cleanup`, `prune_expired` | Toàn bộ dựa vào git |
| Scope phiên | `security/workspace_access.py` | `session.metadata["workspace_scope"]`, kiểm tra tuyệt đối + tồn tại; **không** yêu cầu git |
| Cài đặt theo repo | `RepoConfig`: `acceptance`, `base_ref`, `backend` | Sẽ mất nếu bỏ `repos` |
| Backend `pi`/`agy` | `coding/backends/` | Không đòi git (đã xác nhận); chỉ cần `cwd` |

## 3. Quyết định thiết kế

| ID | Quyết định | Lý do |
|----|-----------|-------|
| D1 | Đọc project từ **`session.metadata["workspace_scope"]`** qua `workspace_scope_from_metadata`, không dùng ContextVar | Dùng được ở tool, `/code`, room chạy nền |
| D2 | Chỉ coi scope là nguồn khi metadata **có khoá** `workspace_scope` (người dùng đã chọn rõ). Không có → hành vi cũ (`repos`); `repos` rỗng → từ chối, nhắc chọn thư mục | Không biến workspace mặc định thành repo |
| D3 | Tham số `repo` của LLM chỉ được nhận khi trùng thư mục scope hoặc nằm trong `repos`. LLM không tạo ra niềm tin mới | Bảo toàn tác dụng của allowlist |
| D4 | `coding.repos` thành **profile tuỳ chọn** theo đường dẫn (`acceptance`, `base_ref`, `backend`); khớp thì dùng, không khớp dùng mặc định. **Không** đọc cấu hình từ file trong repo | `acceptance` là lệnh được thực thi; repo clone về có thể chứa lệnh độc |
| D5 | Phân loại thư mục: git có commit → `worktree`; thư mục con của repo → `worktree` trên toplevel, `cwd = worktree/<rel>`; không git / git chưa có commit → `direct` theo chính sách `non_git` | Tách rõ hai đường chạy |
| D6 | `coding.non_git`: `ask` (mặc định) \| `direct` \| `refuse`. `ask` = cần người dùng đồng ý một lần cho **(phiên, đường dẫn)**, lưu `session_state["coding"]["direct_ok"]` | Tool không hỏi được người dùng; sự đồng ý đến từ UI/lệnh, không từ LLM |
| D7 | `direct` luôn chụp **snapshot** trước khi chạy: sao chép vào `worktree_base/<id>/snapshot` nếu ≤ `snapshot_max_mb` (200); vượt ngưỡng → chỉ manifest (đường dẫn, kích thước, hash file ≤ 5 MB). Bỏ qua `.git`, `node_modules`, `.venv`, `__pycache__`, `dist`, `build` | Cho phép hoàn tác và so sánh |
| D8 | Mỗi thư mục chỉ có **một task `direct` đang chạy** | Không có cách ly; hai task sẽ ghi đè nhau |
| D9 | Task `direct` có `mode="direct"`, `workdir=<project>`; `worktree=""`. **`cleanup`, `prune_expired`, `discard` không bao giờ `rmtree` `workdir`**, chỉ xoá thư mục snapshot | Tránh xoá nhầm dữ liệu người dùng |
| D10 | `diff` ở `direct`: danh sách `added/modified/deleted` + diff văn bản cho file ≤ 64 KB nếu có snapshot, cắt ở `DIFF_MAX_CHARS` | Tài liệu/slide nhị phân không có diff ý nghĩa |
| D11 | `discard` ở `direct` khôi phục từ snapshot **chỉ các file có trong danh sách thay đổi**; file bị sửa sau thời điểm kết thúc task → từ chối trừ khi `force` | Không đè lên chỉnh sửa của người dùng |
| D12 | `/code merge` ở `direct`: trả lời "thay đổi đã áp dụng trực tiếp; dùng `/code discard` để hoàn tác" | Không có nhánh để merge |
| D13 | **Đã chốt:** `access_mode` (`restricted`/`full`) không chặn coding. Backend chỉ nhận vị trí qua `cwd`: `agy` có `--add-dir` (mở rộng workspace) và `--sandbox` (hạn chế terminal), không có cờ khoá vào workspace và adapter đã dùng `--dangerously-skip-permissions`; `pi` chưa kiểm chứng cờ nào (adapter chỉ truyền `--tools/--no-approve/--no-extensions`). Ranh giới thật = thư mục người dùng chọn + worktree/snapshot + cổng `allow_unsandboxed` | Không ép được giới hạn ở tầng backend; hộp xác nhận `direct` phải nói rõ điều này |
| D14 | **Đã chốt:** không khoá task `direct` khi agent chính đang chạy turn trong cùng phiên | Quyết định của người dùng; chỉ ghi chú rủi ro ghi đè trong tài liệu |

## 4. Danh sách task

Cỡ: **S** ≤ nửa ngày, **M** ~1 ngày, **L** 2–3 ngày.

### T-P0 Resolver dự án + ranh giới tin cậy — M — **đã xong**
- Làm xong: `coding/project.py` (`resolve_project`, `ProjectTarget`, `ProjectError`), `admit` tự tra phiên (nên room `_run_guest` được hưởng luôn), `validate_task_repo` và 3 chỗ trong `commands.py` (merge/discard/resume) đã dùng nó — kéo sớm từ T-P4 để task admit từ thư mục dự án vẫn merge được. Tra phiên lỗi (vd. service giả trong test) → rơi về `coding.repos`. Test: `test_project.py`.
- Mới `coworker/coding/project.py`:
  ```python
  @dataclass(frozen=True)
  class ProjectTarget:
      path: Path
      profile: RepoConfig | None
      source: Literal["scope", "config"]

  def resolve_project(session: Any | None, cfg: CodingAgentConfig, repo_arg: str | None) -> ProjectTarget
  ```
  - Thứ tự: scope phiên (D2) → repo duy nhất trong `repos` → lỗi rõ ràng. `repo_arg` theo D3.
  - `profile` = mục `repos` có đường dẫn trùng (so `resolve()`).
- `runner.admit` nhận `ProjectTarget` thay vì tự chọn repo; giữ chữ ký cũ làm lớp bọc.
- `workspace.validate_repo` giữ nguyên (dùng cho `repos`); thêm `validate_task_repo(task)` cho task đã admit (D-notes §5).
- Test `tests/coworker/coding/test_project.py`: scope thắng; không scope + 1 repo; không scope + 0 repo → lỗi; `repo_arg` lạ bị từ chối;
  `repo_arg` bằng scope được nhận; profile khớp áp `acceptance/base_ref/backend`; Windows: khác hoa-thường/dấu `\`.

### T-P1 Phân loại thư mục git — S (phụ thuộc T-P0) — **đã xong**
- Làm xong: `workspace.inspect_project` → `ProjectKind` (`git` / `git_subdir` / `git_empty` / `non_git`); `create_worktree` cắt từ toplevel thật và báo lỗi rõ cho repo chưa có commit / thư mục không phải git (T-P2 sẽ thay lỗi `non_git` bằng chế độ `direct`); `CodingTask.subdir` + `run_dir`: harness, vòng sửa lỗi, `acceptance` và `/code resume` chạy ở `worktree/<subdir>`, còn commit/diff/merge/cleanup chạy ở gốc repo. Test: `test_project_kind.py` (repo thật, thư mục con, rỗng, không git, đường dẫn có dấu cách/Unicode). `git_empty` hiện báo lỗi; chưa quyết định xử lý như `direct` (xem T-P2).
- `workspace.py`: `inspect_project(path) -> ProjectKind` (`git`, `git_subdir(toplevel, rel)`, `git_empty`, `non_git`) bằng
  `git rev-parse --show-toplevel` và `--verify HEAD`. Dùng `toplevel` thật (hiện đang bị bỏ qua).
- `create_worktree`: dùng `toplevel`; backend `cwd = worktree / rel` khi là thư mục con. `merge/cleanup` dùng `toplevel`.
- Test: repo thường, thư mục con, repo rỗng, thư mục thường, đường dẫn có khoảng trắng/Unicode (tạo repo tạm bằng `git init`).

### T-P2 Chế độ `direct` — L (phụ thuộc T-P0, T-P1) — **đã xong**
- Làm xong: `coding/direct.py` (snapshot copy/manifest, `diff_manifest`, `text_diff`, `restore` có kiểm tra mtime), `CodingTask` (`mode/workdir/snapshot/changes/finished_at`), `TaskRegistry.count_active_direct`, `CodingRunner.admit_async` (chọn chế độ, đồng ý, khoá D8; giải phóng slot khi lỗi) — tool `coding_agent` và room dùng bản async, `admit` đồng bộ giữ nguyên; `execute_task` có nhánh `direct`, lỗi setup nay được đánh dấu `error` và báo lại thay vì mất trong task nền; thông báo kết quả riêng cho `direct`. Kéo sớm từ T-P3: `non_git` (`ask`/`direct`/`refuse`, mặc định `ask`), `snapshot_max_mb` và `direct_allowed/grant_direct` (lưu ở `session_state["coding"]["direct_ok"]`) để chế độ `direct` an toàn ngay từ đầu — T-P3 còn phần API/lệnh/UI để người dùng cấp quyền. Repo `git` chưa có commit được coi như `direct`. Chưa làm (T-P4): `/code discard|merge|diff` và hành động `diff` của tool cho task `direct`.
- Mới `coworker/coding/direct.py`:
  ```python
  @dataclass(frozen=True)
  class Manifest: files: dict[str, FileInfo]          # rel path -> (size, mtime_ns, sha256|None)
  def take_snapshot(project: Path, dest: Path, *, max_mb: int) -> Manifest   # copy hoặc manifest-only
  def diff_manifest(before: Manifest, project: Path) -> Changes              # added/modified/deleted
  def text_diff(snapshot: Path, project: Path, changes: Changes, *, limit: int) -> str
  def restore(snapshot: Path, project: Path, changes: Changes, *, since: float, force: bool) -> RestoreResult
  ```
- `tasks.py` `CodingTask`: thêm `mode: Literal["worktree","direct"]="worktree"`, `workdir: str=""`, `snapshot: str=""`,
  `changes: dict[str, list[str]]` (mặc định rỗng; `from_dict` đã lọc khoá lạ nên file cũ vẫn đọc được).
- `TaskRegistry.count_active_direct(workdir)` cho khoá D8.
- `runner.execute_task`: nhánh `direct`:
  1. snapshot → chạy backend với `cwd=workdir` → bỏ `commit_uncommitted_changes`/`get_diffstat`/`get_commits`;
  2. sau mỗi vòng: `diff_manifest` → `task.changes`, `task.diffstat` = tóm tắt dạng "3 added, 5 modified, 1 deleted";
  3. `acceptance` chạy với `cwd=workdir`; vòng sửa lỗi giữ nguyên.
- `_format_delivery_message`: nhánh `direct` ghi "Changed in place (no branch)" thay cho "Commits… on branch"; lời nhắc
  cuối dùng `/code discard` thay vì `merge`.
- Test `tests/coworker/coding/test_direct.py`: snapshot copy và manifest-only (vượt ngưỡng); bỏ qua thư mục loại trừ; diff
  added/modified/deleted; restore chỉ file đã đổi; restore từ chối khi người dùng sửa sau đó; `rmtree` không bao giờ trúng
  `workdir` (kiểm `cleanup`, `prune_expired`, `discard`); khoá D8; backend giả sửa file thật → `task.changes` đúng.

### T-P3 Đồng ý và cấu hình `non_git` — M (phụ thuộc T-P2) — **đã xong**
- Làm xong: section `coding` của `session_api` (`{direct_ok, path}`, chỉ nhận đúng thư mục dự án của chat); `/code direct allow|revoke|status`; `status.coding.project` (`path`, `non_git`, `direct_allowed`, `pending_direct`); khi admit bị chặn vì chưa đồng ý, backend ghi `pending_direct` để UI hỏi người dùng (không phải LLM); hộp xác nhận `CoworkerDirectConfirm` trong header (nêu rõ cảnh báo D13); tab Coding có `non_git` và `snapshot_max_mb`; `admit_async` kiểm tra cổng `allow_unsandboxed` sớm và chỉ đường tới Settings thay vì `PermissionError` trần. i18n en + vi. Test: `test_direct_consent.py`, `coworker-direct-confirm.test.tsx`, `coworker-settings.test.tsx`.
- **Sửa lỗi có sẵn (phát hiện khi làm route):** `ws_http.py` thiếu `persona` trong danh sách action/route, nên chọn persona trên UI trả `404 unknown WebUI mutation action`. Danh sách section nay là một hằng số `_COWORKER_SECTIONS` dùng cho cả đường dẫn mutation, action WS và route, kèm test khẳng định nó bằng `session_api.SECTIONS`.
- Chưa làm: nút "Khởi tạo git" trên hộp xác nhận (thuộc T-P6); đổi tên mục Repositories thành profile (T-P5).
- `config.py` `CodingAgentConfig`: `non_git: Literal["ask","direct","refuse"]="ask"`, `snapshot_max_mb: int = Field(200, ge=1)`.
- `session_api.py`: section `coding` — `{direct_ok: bool, path: str}`; chỉ ghi khi `path` trùng scope hiện tại.
  `ws_http.py`: mở rộng regex mutation thêm `coding` (đổi nhỏ, theo D7 của plan advisor-interaction).
- `admit`: `ask` mà chưa đồng ý → lỗi `needs_confirmation` kèm đường dẫn; tool trả cho LLM câu nhắc "ask the user to
  confirm direct editing". Lệnh `/code direct allow` tương đương nút trên UI.
- `settings_api.py` + `CoworkerSettings.tsx` (tab Coding): select `non_git`, ô `snapshot_max_mb`.
- Hộp xác nhận ghi rõ: backend có thể sửa/xoá file trong thư mục này và không bị giới hạn bởi chế độ truy cập `restricted`.
- Nếu `allow_unsandboxed` của backend đang `false` (và `coding.sandbox="none"`) thì lỗi `admit` nêu đúng nguyên nhân, kèm
  hướng dẫn bật trong Settings → Coworker → Coding, thay vì `PermissionError` trần.
- Test: `ask` chưa đồng ý bị chặn; đồng ý đúng đường dẫn mới mở; đổi project → mất hiệu lực; `refuse`; `direct` bỏ qua hỏi;
  `test_session_api.py` cho section mới.

### T-P4 Cập nhật tool, lệnh, room — M (phụ thuộc T-P2) — **đã xong**
- Làm xong: `CodingRunner.direct_diff_text / refresh_direct_changes / discard_direct` dùng chung cho tool và lệnh; tool `coding_agent`: `diff` cho task `direct` (danh sách file + diff văn bản từ snapshot, cắt ở `DIFF_MAX_CHARS`), `status/result` có `mode` và `changes`, mô tả `repo` và công cụ cập nhật; `/code list|status|diff` hiểu `direct`, `/code merge` báo không có gì để merge, `/code discard <id> [force]` khôi phục từ snapshot (bỏ qua file người dùng sửa sau đó, `force` để ghi đè), `/code resume` chạy ở thư mục dự án và tính lại thay đổi; `status.coding.tasks[]` có `mode` và `changes`; directive CODING thêm một mệnh đề về `/code discard`. Room (`_run_guest`) đã dùng `admit_async` từ T-P2. Test: `test_direct_ops.py`.
- `tools.py`: `repo` mô tả lại ("tuỳ chọn; mặc định là thư mục dự án của phiên"); `diff` hỗ trợ `direct` (D10); `result/status` hiện `mode`.
- `commands.py`: `merge/discard/resume` dùng `validate_task_repo` và `workdir`; D11/D12; `/code list` hiện cột mode.
- `room/scheduler.py:257 _run_guest`: lấy `ProjectTarget` từ session `room.session_key` (D1) thay vì `admit` trần.
- Test: cập nhật `test_diff_action.py`, `test_shared_registry.py`, test room/commands hiện có; thêm ca `direct`.

### T-P5 WebUI — M (phụ thuộc T-P3, T-P4)
- `settings`: mục "Repositories" đổi thành "Project profiles (tuỳ chọn)" kèm dòng giải thích; thêm cài đặt `non_git`.
- Thẻ coding (`CoworkerMessageCard`): badge `worktree`/`direct`; ở `direct` hiện danh sách file đổi (+/~/−) thay cho diffstat.
- Hộp xác nhận "Cho phép sửa trực tiếp thư mục này (không phải git)" gọi `setCoworkerCoding`.
- i18n `coworker.coding.*` (en + vi đầy đủ). Test vitest cho thẻ và hộp xác nhận.

### T-P6 `/code init` — S (phụ thuộc T-P1)
- `/code init` liệt kê file sẽ commit và bản `.gitignore` đề xuất; `/code init confirm` mới thực hiện `git init`, ghi
  `.gitignore`, commit đầu. Không bao giờ chạy ngầm.
- Chỉ cho thư mục `non_git` (không nằm trong repo cha) và là scope của phiên; không dùng được cho đường dẫn tuỳ ý.
- Commit đầu dùng danh sách file đã hiển thị và `.gitignore` đề xuất (`.env`, khoá, `node_modules`, `.venv`, media lớn); sau đó
  thư mục chuyển sang chế độ `worktree`.
- Thêm nút "Khởi tạo git" trên hộp xác nhận `direct` (T-P5) gọi cùng luồng.
- Test: không chạy khi nằm trong repo cha; bỏ qua file khớp `.gitignore`; cần `confirm`; sau init `inspect_project` trả `git`.

### T-P8 Sửa lỗi hiển thị nút header chồng lấn — S (độc lập, làm trước được)
- **Nguyên nhân:** `ThreadHeader.tsx` `controlsClassName` có `[&_button]:h-7 [&_button]:w-7` ép **mọi** button con thành ô vuông
  28 px; selector này thắng `h-8`/`px-2.5` của các pill nên persona, advisor, cache (và chip participants) bị bóp hẹp, chữ tràn và chồng lên nhau.
- **Sửa:** quy tắc ô vuông chỉ áp cho nút icon (`[&_button:not([data-header-pill])]`); thêm `data-header-pill` cho nút persona,
  advisor, prompt cache và chip participants.
- Test `webui/src/tests/thread-header-pills.test.tsx`: class của nhóm nút loại trừ pill; chip participants có `data-header-pill`.
- Kiểm tra bằng mắt: chiều rộng 1280 / 768 / 390 px, light + dark, khi cả ba nút cùng hiển thị.
- Commit: `fix(webui): stop header pills being squeezed into square icon buttons`.
- Trạng thái: **đã sửa code, chưa chạy test/build** (môi trường thiếu bun).

### T-P7 Tài liệu & kiểm thử thủ công — S
- `docs/coworker/README.md`: mục Coding — nguồn project, hai chế độ, chính sách `non_git`, giới hạn của snapshot; bảng cấu hình mới.
- Cập nhật `advisor-webui.md` (mục deviations) trỏ sang plan này.

#### Kịch bản E2E thủ công
0. Bật `allow_unsandboxed` cho backend dùng thử; để `false` thì lỗi `admit` phải nêu đúng nguyên nhân.
1. Phiên mới, chọn repo git bằng picker, không khai báo `repos` → `coding_agent start` chạy, có worktree, `/code merge` OK.
2. Chọn thư mục con của monorepo → worktree ở toplevel, backend chạy đúng thư mục con.
3. Chọn thư mục tài liệu (không git) → lần đầu bị hỏi đồng ý; đồng ý → chạy `direct`; thẻ hiện file đổi.
4. `/code discard` ở task `direct` → file được khôi phục; file người dùng vừa sửa tay không bị đè.
5. Hai task `direct` cùng thư mục → task thứ hai bị từ chối.
6. LLM truyền `repo=<đường dẫn lạ>` → bị từ chối.
7. Phiên Telegram không có scope, `repos` rỗng → từ chối, nhắc chọn project trên WebUI.
8. Thư mục thường → `/code init` (xem file, `confirm`) → thư mục chuyển sang worktree.
9. Thư mục lớn (> `snapshot_max_mb`) → chạy với manifest-only, `discard` báo không khôi phục được nội dung.

## 5. Ghi chú kỹ thuật

- Task đã admit lưu `repo`/`workdir` trong registry (do chính hệ thống ghi) → merge/discard/resume tin `t.repo`, không đối chiếu lại `repos`.
- `asyncio` task tạo bằng `spawn_background` sau `admit` đã mang sẵn `ProjectTarget`; không phụ thuộc ContextVar.
- Cổng cache: không đụng payload gửi LLM nên không ảnh hưởng prompt cache.

## 6. Rủi ro

| Rủi ro | Giảm thiểu |
|--------|-----------|
| Backend ghi/xoá file thật trong `direct` | Snapshot bắt buộc, khoá D8, đồng ý rõ ràng D6, D11 |
| `rmtree` nhầm thư mục người dùng | D9 + test chuyên biệt |
| Snapshot lớn làm chậm/đầy đĩa | Ngưỡng `snapshot_max_mb`, thư mục loại trừ, manifest-only |
| Agent chính và task `direct` cùng sửa một file | Chấp nhận (D14); ghi chú trong tài liệu |
| Đường dẫn Windows (hoa-thường, `\`, symlink) | So sánh qua `resolve()`; test riêng |
| Gỡ allowlist gây hở bảo mật | D2/D3; test từ chối `repo` lạ |

## 7. Câu hỏi còn mở

Không còn. D13, D14 và T-P6 đã được chốt.

## 8. Thứ tự & commit

T-P8 (độc lập) · T-P0 → T-P1 → T-P2 → T-P3 → T-P4 → T-P5 → T-P6 → T-P7.

1. `feat(coworker): resolve coding project from session scope` (T-P0, T-P1)
2. `feat(coworker): direct mode for non-git project directories` (T-P2)
3. `feat(coworker): non-git consent and settings` (T-P3)
4. `feat(coworker): coding tool, commands and room use project target` (T-P4)
5. `feat(webui): coding project profiles and direct-mode card` (T-P5)
6. `feat(coworker): explicit /code init` (T-P6)
7. `docs(coworker): coding project scope` (T-P7)
8. `fix(webui): stop header pills being squeezed into square icon buttons` (T-P8, có thể làm trước)

Mỗi bước: `ruff check nanobot/`, `uv run --no-sync basedpyright`, `pytest tests/coworker -q`,
`cd webui && bun run test && bun run build` khi có đổi WebUI.
