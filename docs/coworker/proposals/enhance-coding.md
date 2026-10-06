❯ Những cách thức coding hiện tại có thể thực hiện với codebase này là gì?

✻ Thought for 7 seconds [ctrl+o to expand]

⠶ Đây là câu hỏi khảo sát. Tôi sẽ rà lại các đường "coding" hiện có trong hệ thống (không chỉ đường Pi) để trả lời chính xác theo code hiện tại.

 EXPLORE  [Enumerate coding paths]
 └  Done  (4m 13s | 1384.7k tokens)

✻ Thought for 2 seconds [ctrl+o to expand]

⠶ Dưới đây là toàn bộ các "đường" thực hiện coding hiện có trong codebase (sau Phase 5). Chúng hội tụ về CodingRunner.admit → orchestrator phase, nhưng điểm khởi phát khác nhau.

  1. Agent tự sửa (không giao Pi)

  - Dùng tool built-in: read_file, write_file, edit_file, list_dir, apply_patch, exec/shell.
  - Directive directives.CODING (coworker/directives.py:226-250) quy định: 1–2 file, sửa nhỏ → tự dùng apply_patch; từ 3 file / tính năng mới / cần chạy test → giao Pi. Directive chỉ bật
  khi coding.enabled.

  2. Giao cho Pi qua tool coding_agent (coworker/coding/tools.py)

  - start — nhận contract (objective, context ≥ 120 ký tự, acceptance_criteria, constraints, out_of_scope, mode, repo, base, acceptance, files, wait); chạy trong worktree (git) hoặc
  in-place (direct).
  - approve, revise_plan, answer (trả lời câu hỏi ask_coordinator), steer, abort, status, result, diff.
  - mode: plan_first (có bước lập kế hoạch) hoặc auto; wait=true chỉ cho task nhanh (≤ 10 phút).
  - Lưu ý: không còn tham số backend; mọi giá trị khác "pi" bị quy về Pi.

  3. Lệnh slash /code (coworker/coding/commands.py)

  - list, status <id>, diff <id>, steer <id> <msg>, abort <id>, merge <id>, discard <id> [force], resume <id> [msg], doctor, direct allow|revoke|status, init [confirm|cancel].

  4. @-mention (coworker/hook.py:115-147)

  - @pi (và @agy cũ, hiện quy về Pi): chèn note yêu cầu agent gọi coding_agent(action="start", backend="pi", ...) rồi kết thúc lượt.
  - @advisor: yêu cầu consult advisor. @<teammate>: kích hoạt room (định tuyến qua scheduler, không qua coding trực tiếp).

  5. Room teammate có backend coding (room/scheduler.py:_run_guest)

  - room_delegate tới teammate có agent.backend="pi" → CodingRunner.admit_async + execute_task(wait=True) trong room.

  6. Chế độ direct cho dự án không phải git (coding.non_git)

  - ask (cần user xác nhận /code direct allow), direct (sửa tại chỗ ngay), refuse (từ chối).
  - Có snapshot trước khi chạy; hoàn tác bằng /code discard <id>; guard chặn thư mục nhạy cảm; WriteWatch phát hiện ghi ngoài dự án.

  7. Cách nó chạy bên trong (mọi đường trên đều qua đây)

  - State machine: prepare → plan → await_approval → implement → review → fix → deliver.
  - Reviewer độc lập: tiến trình Pi mới, --no-session, dựa report_result(kind='review').
  - Extension nanobot-bridge.ts cưỡng chế policy bằng code: chặn ghi ngoài write_roots/mode plan-review, chặn deny_commands/deny_read, cổng agent_before_settle chạy acceptance và tự
  continue tối đa settle_max_continuations.

  8. Kích hoạt gián tiếp

  - Turn inject: coding_question, coding_plan, [auto-coding-result] — đưa agent chính quay lại và có thể gọi thêm coding_agent.
  - Cron/heartbeat/workflow: không nối trực tiếp coding; nhưng một turn do cron/workflow tạo ra vẫn có thể gọi coding_agent như turn thường.

  Chặn chung: mọi đường đều qua CodingRunner.admit, raise nếu coding.enabled=False; tool coding_agent bị ẩn khỏi model khi disabled.

  Tóm một dòng: agent tự sửa (tool file), giao Pi (coding_agent//code/@pi/room teammate), chạy worktree hoặc direct, với phase + reviewer + gate bên trong.

❯ Review danh sách các cách thực hiện coding hiện có, cách nào đảm bảo chất lượng tốt nhất, tương đương chạy trực tiếp với coding agent như Pi/CommandCode/Cline/OpenCode ?

✻ Thought for 15 seconds [ctrl+o to expand]

⠶ Trả lời ngắn gọn: đường coding_agent(action="start", mode="plan_first") + review (mặc định bật) là chất lượng cao nhất và là đường duy nhất chạy một coding agent thật (Pi) với đủ plan →
  implement → reviewer → acceptance gate. Nó có thể vượt "chạy trực tiếp một agent" ở phần kiểm chứng, nhưng thua ở phần tương tác/duyệt kế hoạch liên tục.

  Xếp hạng chất lượng (cao → thấp)

  - 1. coding_agent plan_first + review — đầy đủ: Pi lập kế hoạch (read-only), implement trong worktree, một tiến trình Pi reviewer độc lập đọc diff và chạy test, cổng agent_before_settle
  tự chạy acceptance và continue tới khi đạt. Đây là thứ khi chạy trực tiếp bạn phải tự làm bằng tay.
  - 2. coding_agent auto + review — bỏ bước plan, nhanh hơn, hợp task nhỏ/rõ ràng; mất lớp phòng thủ của kế hoạch.
  - 3. Room teammate backend="pi" — chạy đúng pipeline trên nhưng trong room, wait=True, ít tương tác tinh chỉnh giữa chừng.
  - 4. /code resume — tiếp tục task gián đoạn, không phải đường bắt đầu mới.
  - 5. Agent tự sửa (apply_patch/file tools) — không phải coding agent; chỉ hợp 1–2 file, sửa nhỏ.
  - 6. direct mode — có snapshot/undo nhưng sửa tại chỗ, không worktree isolation, rủi ro cao hơn; chỉ nên cho dự án không git.

  So với chạy trực tiếp Pi / CommandCode / Cline / OpenCode

  - Mạnh hơn (chạy trực tiếp 1 agent không có): reviewer độc lập (người làm ≠ người chấm, không thấy transcript người làm), acceptance gate tự continue, policy cưỡng chế bằng code
  (nanobot-bridge), worktree/snapshot để merge/undo.
  - Yếu hơn / khác biệt:

  - Chỉ dùng Pi làm executor. CommandCode/Cline/OpenCode không phải backend — plan đã loại mọi harness khác (Agy, Claude Code, Codex, Gemini CLI, ACP). Muốn chạy đúng Cline/OpenCode thì
  codebase này không hỗ trợ.
  - Chất lượng bị chặn trên bởi contract do agent chính viết, không phải bạn viết. Contract mơ hồ (objective không đo được, acceptance_criteria yếu) → kết quả yếu dù Pi mạnh.
  - Thiếu human-in-the-loop ở bước duyệt plan: plan_approval="auto" (mặc định) tự duyệt plan ≤ 6 bước; "always" hiện là ngõ cụt (approval continuation chưa làm — mục D trong Further
  Works).
  - Reviewer dễ trùng model người làm nếu không cấu hình phases.review.model khác → tính độc lập giảm.

  Cấu hình để đạt chất lượng cao nhất hiện tại

  - mode="plan_first", review=true, fix_rounds ≥ 1.
  - coding.pi.phases.review.model khác (và nếu được, mạnh hơn) implement.model; thinking cho review cao.
  - settle_max_continuations = 2–3 để gate chịu tự sửa qua vài lượt.
  - Contract tốt: objective đo được, context đầy đủ ngữ cảnh/quyết định đã chốt, acceptance_criteria kiểm chứng được, out_of_scope rõ.
  - Luôn giữ khâu con người ở lúc merge: /code diff <id> (hoặc advisor review diff) rồi mới /code merge.

  Kết luận: Không có đường nào hoàn toàn tương đương chạy trực tiếp — chạy trực tiếp cho bạn vòng lặp tương tác liên tục (steer, duyệt từng bước, đổi hướng). Đường gần nhất và tốt nhất là
  coding_agent plan_first + review, vượt trội ở kiểm chứng tự động nhưng thua ở tương tác. Để bù khoảng trống đó, bạn có hai đòn bẩy: (1) dùng steer/abort/resume để điều hướng giữa chừng,
  và (2) khi nào làm xong "approval continuation" (Further Works D) thì bật plan_approval="always" để duyệt kế hoạch trước khi Pi đụng code.

❯ đề xuất hướng cập nhật mã nguồn để tập trung vào hướng đạt chất lượng cao nhất này, hướng direct mode vẫn duy trì như cũ hoặc gợi ý sửa theo hướng tối ưu hơn

✻ Thought for 19 seconds [ctrl+o to expand]

⠶ Đây là đề xuất hướng cập nhật, tập trung làm cho đường coding_agent plan_first + review trở thành đường chất lượng cao nhất và ổn định. Tôi chia theo mức ưu tiên, mỗi mục có "vì sao tăng
  chất lượng" và vị trí code.

  A. Ưu tiên 1 — biến plan_first + review thành đường "mặc định chất lượng cao"

  - A1. Approval continuation (nối awaiting_approval → implement/plan). Đây là đòn bẩy lớn nhất. Hiện plan_approval="always" là ngõ cụt, approve/revise_plan là stub. Cần: khi approve,
  giữ/khởi động lại Pi theo pi_session_file rồi chạy tiếp Implement; khi revise_plan, follow_up lại Plan. Lý do: đưa con người vào đúng điểm quan trọng nhất — duyệt kế hoạch trước khi Pi
  đụng code — ngang bằng chạy tương tác.

  - Vị trí: orchestrator.py (thêm approve_task/revise_task), tools.py (approve/revise_plan), commands.py (tuỳ chọn /code approve <id>).
  - A2. Reviewer độc lập thực sự bằng cấu hình + code. (a) thêm cảnh báo/nhắc khi phases.review.model trùng implement.model; (b) chạy reviewer với --tools chỉ-đọc (thay vì chỉ dựa prompt +
   mode=review). Lý do: reviewer là điểm vượt trội so với chạy 1 agent; độc lập về model + tool làm nó đáng tin hơn.
    - Vị trí: review.py, orchestrator._review_and_fix, config validation settings_api._check_phase_models.
  - A3. Plan phải "bao phủ" acceptance_criteria. Tự duyệt (plan_approval=auto) chỉ khi plan_steps khớp đủ các tiêu chí, không chỉ "≤ N bước". Lý do: tránh duyệt plan sơ sài rồi implement
  lệch hướng.
    - Vị trí: orchestrator.py (logic auto_approved), prompt plan, reviewer prompt.

  B. Ưu tiên 2 — nâng chất lượng contract (đầu vào của mọi thứ)

  - B1. Siết directive cho agent chính. Đã có "3 file → giao Pi"; thêm "cần chạy test/lint/refactor → giao Pi kể cả 1–2 file". Lý do: giảm trường hợp agent tự apply_patch cho việc đáng lẽ
  phải giao Pi.
  - B2. Kiểm tra contract trước khi start. validate() hiện chỉ đòi objective/context/acceptance_criteria. Thêm cảnh báo khi mode=plan_first mà thiếu acceptance (lệnh kiểm thử) hoặc tiêu
  chí không đo được. Lý do: contract yếu là nút thắt chất lượng lớn nhất.
    - Vị trí: contract.py, tools.py (start).

  C. Ưu tiên 3 — bằng chứng & quan sát để "đóng vòng" chất lượng

  - C1. Báo cáo delivery đầy đủ bằng chứng. Đã ghi coding_runs; bổ sung hiển thị settle_continuations (gate tự sửa mấy lần), verdict reviewer + findings, export_html link ở /code result và
   inspector. Lý do: cho bạn thấy rõ task "đạt" là nhờ kiểm chứng thật, không phải Pi tự nhận.
    - Vị trí: format_delivery_message, status.py, inspector.

  D. Direct mode — khuyến nghị: giữ như cũ, 1 gợi ý tùy chọn

  - Giữ nguyên snapshot + guard + /code discard — đủ an toàn cho docs/slides. Không nên đầu tư thêm trước mắt.
  - Gợi ý tối ưu (làm sau, nếu cần): (a) chủ động gợi ý /code init khi phát hiện thư mục chưa có git, để hầu hết dự án "lên" được worktree mode; (b) tuỳ chọn "staging copy": chạy Pi trên
  bản copy rồi apply diff về thư mục gốc khi pass review — cho isolation nhưng vẫn giữ trải nghiệm in-place. Lý do: direct mode hiện thiếu isolation, nhưng chi phí sửa không tương xứng với
   lợi ích khi đã có worktree cho mọi repo có git.

  E. Không nên đụng (giữ nguyên)

  - Phases state machine, cổng nanobot-bridge (agent_before_settle + policy), review loop, wait=true — đang đúng và là nền tảng chất lượng.

  Thứ tự triển khai đề xuất: A1 → A2 → A3 → B1/B2 → C1, rồi mới xét D (tuỳ chọn). A1 và A2 mang lại nhiều chất lượng nhất trên mỗi dòng code.