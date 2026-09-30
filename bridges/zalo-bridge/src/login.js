import fs from "node:fs/promises";
import path from "node:path";
import { Zalo } from "zca-js";

const sessionPath = process.env.SESSION_PATH || "./session.json";
const qrImagePath = "./qr.png";

console.log("Khởi động tiến trình đăng nhập Zalo qua mã QR...");
const zalo = new Zalo();

try {
  await zalo.loginQR({}, async (event) => {
    if (event.type === 0) {
      // QRCodeGenerated
      const rawImage = event.data.image || "";
      const base64Data = rawImage.replace(/^data:image\/\w+;base64,/, "");
      await fs.writeFile(qrImagePath, Buffer.from(base64Data, "base64"));
      console.log(`\n============================================================`);
      console.log(`[!] ĐÃ TẠO MÃ QR THÀNH CÔNG!`);
      console.log(`-> File ảnh đã được lưu tại: ${path.resolve(qrImagePath)}`);
      console.log(`-> Mở ảnh 'qr.png' và dùng app Zalo trên điện thoại quét mã.`);
      console.log(`============================================================\n`);
    } else if (event.type === 1) {
      // QRCodeExpired
      console.error("\n[✗] Mã QR đã hết hạn. Vui lòng chạy lại lệnh để lấy mã mới.");
      process.exit(1);
    } else if (event.type === 2) {
      // QRCodeScanned
      const name = event.data?.display_name || "người dùng";
      console.log(`[✓] Đã nhận diện quét QR từ: ${name}. Vui lòng bấm 'Đăng nhập' trên điện thoại...`);
    } else if (event.type === 3) {
      // QRCodeDeclined
      console.error("\n[✗] Yêu cầu đăng nhập đã bị từ chối trên điện thoại.");
      process.exit(1);
    } else if (event.type === 4) {
      // GotLoginInfo
      await fs.mkdir(path.dirname(path.resolve(sessionPath)), { recursive: true });
      await fs.writeFile(sessionPath, JSON.stringify(event.data, null, 2), "utf-8");
      console.log(`\n[✓] ĐĂNG NHẬP THÀNH CÔNG!`);
      console.log(`-> Đã lưu phiên làm việc vào: ${path.resolve(sessionPath)}`);
      console.log(`-> Bây giờ bạn có thể khởi động bridge bằng lệnh: npm start\n`);

      // Dọn dẹp file qr.png tạm
      try {
        await fs.unlink(qrImagePath);
      } catch {}

      process.exit(0);
    }
  });
} catch (err) {
  console.error("\n[✗] Lỗi trong quá trình đăng nhập:", err?.message || err);
  process.exit(1);
}
