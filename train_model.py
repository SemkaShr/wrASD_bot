import joblib
import pandas as pd
from datasets import load_dataset
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

# 1. Загрузка датасета с Hugging Face
print("Скачиваем датасет...")
dataset = load_dataset("alt-gnome/telegram-spam")
df = pd.DataFrame(dataset['train'])

print(f"Всего сообщений: {len(df)}")
print(df.head())

# 2. Разделение на обучение и тест
X_train, X_test, y_train, y_test = train_test_split(
    df['text'], 
    df['label'], 
    test_size=0.2, 
    random_state=42
)

# 3. Создание пайплайна (Векторизатор + Модель)
# TfidfVectorizer превращает текст в матрицу чисел
# LogisticRegression классифицирует эти числа
pipeline = Pipeline([
    ('tfidf', TfidfVectorizer(ngram_range=(1, 2), max_features=10000)), 
    ('clf', LogisticRegression(solver='liblinear'))
])

# 4. Обучение
print("Обучаем модель...")
pipeline.fit(X_train, y_train)

# 5. Оценка качества
print("Результаты на тестовой выборке:")
predictions = pipeline.predict(X_test)
print(classification_report(y_test, predictions))

# 6. Сохранение модели в файл
model_filename = "spam_detector_model.pkl"
joblib.dump(pipeline, model_filename)
print(f"Модель сохранена в файл: {model_filename}")