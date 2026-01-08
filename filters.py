from aiogram.filters import BaseFilter
from aiogram import types
import joblib
import logging
from db import get_chat_settings, cursor, conn
from config import MODEL_PATH

try:
    spam_pipeline = joblib.load(MODEL_PATH)
    logging.info("ML model loaded from %s", MODEL_PATH)
except Exception as e:
    spam_pipeline = None
    logging.exception("Failed to load ML model (spam_pipeline). ML auto-detection will be disabled.")


class SpamFilter(BaseFilter):
    async def __call__(self, message: types.Message) -> bool:
        if not message.text or message.chat.type == "private":
            return False

        if spam_pipeline is None:
            logging.warning("Spam pipeline not loaded — skipping ML auto-detection.")
            return False

        settings = get_chat_settings(message.chat.id)
        threshold = settings["threshold"]
        logging_enabled = settings["logging"]

        try:
            proba = spam_pipeline.predict_proba([message.text])[0]
            spam_prob = float(proba[1])
        except Exception as e:
            logging.exception("Error while predicting ML probability: %s", e)
            try:
                pred = int(spam_pipeline.predict([message.text])[0])
                spam_prob = 1.0 if pred == 1 else 0.0
            except Exception:
                spam_prob = 0.0

        if logging_enabled:
            try:
                cursor.execute(
                    "INSERT INTO ml_logs (chat_id, message_text, spam_prob, is_deleted) VALUES (?,?,?,?)",
                    (message.chat.id, message.text, spam_prob, int(spam_prob >= threshold))
                )
                conn.commit()
            except Exception:
                logging.exception("Failed to write ml_log to DB")

        logging.info("Chat %s ML prob=%.4f threshold=%.4f", message.chat.id, spam_prob, threshold)
        return spam_prob >= threshold
