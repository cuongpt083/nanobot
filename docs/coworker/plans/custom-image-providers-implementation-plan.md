# Implementation Plan: Hỗ trợ Custom Image Providers (agy2api & OpenAI-compatible) trong Nanobot

_Cập nhật: 05/10/2026 · Repo: `cuongpt083/nanobot`, nhánh `develop`_

---

## 1. Tổng quan & Đặt vấn đề

Nanobot hiện đã sở hữu công cụ tạo ảnh `generate_image` (`nanobot/agent/tools/image_generation.py`), tuy nhiên kiến trúc hiện tại có nhiều hạn chế khi tích hợp với các Gateway/API custom OpenAI-compatible từ bên ngoài (chẳng hạn như `agy2api` tại `http://192.168.100.17:8000/v1`):

1. **Khóa cứng Registry theo chuỗi `"custom"`:** 
   * `_IMAGE_GEN_PROVIDERS` chỉ đăng ký duy nhất key `"custom"`.
   * Người dùng cấu hình nhiều custom provider khác nhau trong `config.json` (ví dụ `"custom-agy-17"`, `"custom-flux"`, `"custom-sd"`) không thể dùng cho image generation. Khi chọn các provider này, hệ thống báo lỗi `"unknown image generation provider"` hoặc `"provider is not available"`.
2. **Danh sách Model hoàn toàn tĩnh (`model_options`):**
   * Đối với Chat Model, Nanobot tự động query `GET {api_base}/v1/models` để gợi ý danh sách model cho người dùng.
   * Nhưng đối với Image Provider, `_image_generation_provider_rows` chỉ đọc thuộc tính tĩnh `model_options` của class Python. `CustomImageGenerationClient` kế thừa tuple rỗng `()`, dẫn đến WebUI không thể hiển thị dropdown model nào từ remote server.
3. **Chưa hỗ trợ `reference_images` cho Custom Provider:**
   * Trong `CustomImageGenerationClient.generate`, Nanobot đang in log warning: `"Custom image generation does not support reference images; ignoring ..."` và bỏ qua toàn bộ ảnh tham chiếu.
   * Trong khi đó, các backend như `agy2api` đã hỗ trợ Image-to-Image / reference images qua mảng `reference_images` (chuỗi base64 data URI).
4. **Kiểm tra `configured` bị trượt:**
   * Khi `image_generation.provider` là `"custom"`, Nanobot chỉ đọc `config.providers.custom`. Nếu người dùng cấu hình thông tin endpoint ở các subkey như `custom-agy-17`, `configured` bị đánh giá là `False` và WebUI từ chối bật tính năng tạo ảnh.

---

## 2. Mục tiêu

1. **Hỗ trợ Named Custom Providers:** Cho phép bất kỳ provider nào có prefix `custom` hoặc có spec custom/openai-compat (như `custom-agy-17`) được sử dụng làm image provider.
2. **Dynamic Model Discovery:** Cho phép WebUI tra cứu danh sách model từ endpoint `/models` hoặc `/v1/models` của custom provider để người dùng dễ dàng lựa chọn trong giao diện.
3. **Hỗ trợ Image-to-Image (Reference Images):** Chuyển đổi file ảnh local sang chuẩn Data URI Base64 khi gửi request đến endpoint `/images/generations` của custom provider.
4. **Tương thích ngược 100%:** Giữ nguyên các hành vi hiện có của các provider mặc định (`openrouter`, `openai`, `gemini`, `minimax`, `ollama`).

---

## 3. Thiết kế chi tiết & Các file cần chỉnh sửa

### 3.1. `nanobot/providers/image_generation.py`
* **Resolve Provider động:**
  * Sửa hàm `get_image_gen_provider(name: str) -> type[ImageGenerationProvider] | None`:
    ```python
    def get_image_gen_provider(name: str) -> type[ImageGenerationProvider] | None:
        if name in _IMAGE_GEN_PROVIDERS:
            return _IMAGE_GEN_PROVIDERS[name]
        # Cho phép mọi custom provider có tiền tố "custom" phân giải về CustomImageGenerationClient
        if name.startswith("custom") or name.startswith("custom-"):
            return CustomImageGenerationClient
        return None
    ```
  * Cập nhật `image_gen_provider_configs(config: Config) -> dict[str, ProviderConfig]`:
    * Quét toàn bộ `config.providers`, bao gồm cả các key tùy biến dạng `custom-*` để đưa vào danh sách `provider_configs` sẵn sàng cho Tool.
* **Cải tiến `CustomImageGenerationClient`:**
  * Thêm xử lý `reference_images`:
    * Thay vì bỏ qua `reference_images`, đọc file và chuyển thành mảng `data:{mime};base64,...`.
    * Đưa mảng này vào `body["reference_images"]` khi gửi request sang `/images/generations`.
  * Hỗ trợ dynamic model listing:
    * Thêm class/instance method `async def fetch_available_models(api_base: str, api_key: str | None) -> list[str]`.

### 3.2. `nanobot/agent/tools/image_generation.py`
* **Inject đầy đủ Provider Configs:**
  * Đảm bảo `self.provider_configs` chứa đầy đủ cấu hình của các custom provider.
  * Trong `_provider_client()`: Khởi tạo `CustomImageGenerationClient` với `api_base` và `api_key` lấy chính xác từ provider được cấu hình trong `self.config.provider`.

### 3.3. `nanobot/webui/settings_capabilities.py`
* **Mở rộng `_image_generation_provider_rows`:**
  * Bổ sung các custom provider xuất hiện trong `config.providers` (ví dụ `custom-agy-17`) vào danh sách rows trả về cho WebUI.
  * Gán label hiển thị tương ứng (vd: `Agy-17 (Custom Image)`).
  * Nếu provider có `api_base`, gọi endpoint `/models` (với timeout ngắn và cache) hoặc fallback về danh sách model đã biết để điền vào `models`.
* **Cập nhật `update_image_generation_settings`:**
  * Chấp nhận các provider hợp lệ được phân giải bởi `get_image_gen_provider`.
  * Kiểm tra trạng thái `configured` dựa trên chính provider config được chọn (chứ không chỉ cố định ở `providers.custom`).

### 3.4. Giao diện WebUI (`webui/`)
* Kiểm tra frontend component quản lý cài đặt Image Generation để đảm bảo dropdown Model nhận diện được danh sách model trả về từ dynamic custom provider rows.

---

## 4. Lộ trình triển khai (Phased Roadmap)

### Phase 1: Core Registry & Runtime Provider Resolution
- [x] Mở rộng `get_image_gen_provider` trong `nanobot/providers/image_generation.py` để hỗ trợ pattern `custom-*`.
- [x] Cập nhật `image_gen_provider_configs` trong `nanobot/providers/image_generation.py` để nạp mọi instance custom provider từ `config.providers`.
- [x] Cập nhật `_provider_client` trong `nanobot/agent/tools/image_generation.py` đảm bảo inject đúng thông tin cấu hình cho các named custom provider.
- [x] Viết unit test trong `tests/agent/tools/test_image_generation.py` kiểm tra:
  * Phân giải thành công `custom-agy-17`.
  * Khởi tạo `ImageGenerationTool` và gọi client với `api_base` của custom provider.

### Phase 2: Hỗ trợ Reference Images (Image-to-Image) cho Custom Client
- [x] Cập nhật `CustomImageGenerationClient.generate` để mã hóa các file trong `reference_images` thành data URI Base64.
- [x] Đính kèm trường `reference_images` vào payload POST `/images/generations`.
- [x] Viết unit test mô phỏng backend tương thích `agy2api` nhận payload có `reference_images`.

### Phase 3: WebUI Settings & Model Discovery
- [x] Cập nhật `_image_generation_provider_rows` trong `nanobot/webui/settings_capabilities.py` để hiển thị các custom provider trong cấu hình.
- [x] Bổ sung dynamic model discovery bằng cách tái sử dụng endpoint `/api/settings/provider-models` sẵn có (`models: null` kích hoạt WebUI `ModelIdPicker` fetch online theo nhu cầu và fallback gõ tay tự do; giữ timeout 10s hiện tại thay vì 2.0s để tránh stall save settings payload).
- [x] Cập nhật validation trong `update_image_generation_settings` để cho phép lưu cấu hình named custom provider.
- [x] Viết test trong `tests/webui/test_settings_capabilities.py`.

### Phase 4: Kiểm thử toàn diện & Tài liệu
- [x] Chạy toàn bộ test suite liên quan của Nanobot (110 tests image generation & settings capabilities passed, 107 settings api passed, basedpyright 0 errors, vitest 82 settings tests passed).
- [x] Cập nhật tài liệu `docs/image-generation.md` và `docs/provider-cookbook.md` hỗ trợ custom providers (`custom-*`), reference images (image-to-image), recipe và `displayName`.
- [ ] **[BLOCKED - Host Unreachable]** Thử nghiệm thực tế với server `agy2api` tại `http://192.168.100.17:8000/v1`:
  * Ping/TCP connect tới `192.168.100.17:8000` bị TimedOut (server offline hoặc khác subnet).
  * Các unit tests mô phỏng đã pass 100%. Khi máy chủ online, có thể kiểm tra trực tiếp qua WebUI Settings hoặc CLI: `nanobot agent -m "Vẽ một chú mèo tam thể"`.

---

## 5. Rủi ro & Chiến lược giảm thiểu

| Rủi ro | Tác động | Giải pháp |
|---|---|---|
| Remote server không phản hồi endpoint `/v1/models` khi mở WebUI | WebUI tải chậm hoặc bị treo | Thiết lập timeout ngắn (2.0s), dùng cache và cho phép người dùng tự gõ text input model nếu fetch thất bại |
| Quá tải dung lượng khi gửi `reference_images` lớn | Tràn bộ nhớ / Request Entity Too Large | Giới hạn tối đa 3 ảnh tham chiếu và tối đa 10MB/ảnh trước khi encode Base64 |
| Trùng lặp cấu hình giữa `custom` và `custom-<name>` | Người dùng bối rối khi chọn provider | Hiển thị rõ `displayName` và `api_base` của từng custom provider trên giao diện WebUI |
