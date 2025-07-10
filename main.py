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
        # Check if error exists
        score = (
            data["lighthouseResult"]["categories"]["performance"]["score"]
            if "lighthouseResult" in data
            else None
        )
        if score is not None:
            # Convert to 0-100 scale
            return int(round(score * 100)), "ok" if score * 100 >= 80 else "not ok"
        else:
            return None, "error"
    except Exception as e:
        return None, "error"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Gửi file Excel chứa danh sách URL vào đây.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.document.get_file()
    file_path = f"/tmp/input_{update.message.document.file_id}.xlsx"
    await file.download_to_drive(file_path)
    try:
        df = pd.read_excel(file_path)
        urls = df.iloc[:, 0].dropna().tolist()  # Lấy URL từ cột đầu tiên
        result = []
        for idx, url in enumerate(urls, 1):
            perf, status = get_performance_score(url)
            result.append({
                "STT": idx,
                "URL": url,
                "Performance": perf if perf is not None else "N/A",
                "Status": status,
            })
        result_df = pd.DataFrame(result)
        output_path = f"/tmp/result_{update.message.document.file_id}.xlsx"
        result_df.to_excel(output_path, index=False)
        await update.message.reply_document(InputFile(output_path, filename="result.xlsx"))
    except Exception as e:
        await update.message.reply_text("Lỗi xử lý file. File phải là Excel, cột đầu là danh sách URL.")
    finally:
        # Xoá file tạm
        try: os.remove(file_path)
        except: pass

def main():
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    app = ApplicationBuilder().token(bot_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.run_polling()

if __name__ == "__main__":
    main()
