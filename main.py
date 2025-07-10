import os
import pandas as pd
import requests
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

PAGESPEED_API_KEY = os.getenv("PAGESPEED_API_KEY")

def get_performance_score(url):
    api_url = (
        f"https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
        f"?url={url}&strategy=mobile&key={PAGESPEED_API_KEY}"
    )
    try:
        r = requests.get(api_url, timeout=30)
        data = r.json()
        if 'error' in data:
            return None, f"error: {data['error'].get('message', '')}"
        if "lighthouseResult" in data and \
           "categories" in data["lighthouseResult"] and \
           "performance" in data["lighthouseResult"]["categories"]:
            score = data["lighthouseResult"]["categories"]["performance"]["score"]
            if score is not None:
                score_int = int(round(score * 100))
                return score_int, "ok" if score_int >= 80 else "not ok"
        return None, "no performance data"
    except Exception as e:
        return None, f"error: {str(e)}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Gửi file Excel (.xlsx) chứa danh sách URL (cột đầu tiên) vào đây.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document:
        await update.message.reply_text("Không nhận được file.")
        return
    file_name = update.message.document.file_name
    if not file_name.endswith(".xlsx"):
        await update.message.reply_text("Chỉ chấp nhận file .xlsx.")
        return
    file = await update.message.document.get_file()
    file_path = f"/tmp/input_{update.message.document.file_id}.xlsx"
    await file.download_to_drive(file_path)
    try:
        df = pd.read_excel(file_path)
        if df.shape[1] < 1:
            await update.message.reply_text("File Excel không có cột nào.")
            return
        urls = df.iloc[:, 0].dropna().tolist()
        if not urls:
            await update.message.reply_text("Không tìm thấy URL nào trong file.")
            return

        # 1. THÔNG BÁO đã nhận file và số link sẽ xử lý
        await update.message.reply_text(f"Đã nhận file. Tổng số link sẽ xử lý: {len(urls)}")

        result = []
        # Gửi tin nhắn trạng thái để cập nhật liên tục
        status_msg = await update.message.reply_text("Bắt đầu kiểm tra link...")

        for idx, url in enumerate(urls, 1):
            perf, status = get_performance_score(url)
            result.append({
                "STT": idx,
                "URL": url,
                "Performance": perf if perf is not None else "N/A",
                "Status": status,
            })
            # Cập nhật log mỗi 2 link, hoặc link cuối
            if idx % 2 == 0 or idx == len(urls):
                await status_msg.edit_text(f"Đã xử lý {idx}/{len(urls)} link...")

        result_df = pd.DataFrame(result)
        output_path = f"/tmp/result_{update.message.document.file_id}.xlsx"
        result_df.to_excel(output_path, index=False)
        await update.message.reply_document(InputFile(output_path, filename="result.xlsx"))
        await update.message.reply_text("Đã hoàn tất. Đã gửi file kết quả.")
    except Exception as e:
        await update.message.reply_text(f"Lỗi xử lý file: {e}")
    finally:
        try: os.remove(file_path)
        except: pass

def main():
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        print("Lỗi: Chưa thiết lập biến môi trường TELEGRAM_BOT_TOKEN")
        exit(1)
    if not PAGESPEED_API_KEY:
        print("Lỗi: Chưa thiết lập biến môi trường PAGESPEED_API_KEY")
        exit(1)
    app = ApplicationBuilder().token(bot_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    print("Bot đã sẵn sàng.")
    app.run_polling()

if __name__ == "__main__":
    main()
