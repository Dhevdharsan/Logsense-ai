import re
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from loguru import logger

PATTERNS = [
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[\.,\d]*Z?"), "<TIMESTAMP>"),
    (re.compile(r"\d{2}:\d{2}:\d{2}[\.,\d]*"), "<TIMESTAMP>"),
    (re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?"), "<IP>"),
    (re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I), "<UUID>"),
    (re.compile(r"\b(req|usr|job|pod|host)-[a-z0-9]+\b", re.I), "<ID>"),
    (re.compile(r"\b(process|pid)\s+\d+\b", re.I), "<PID>"),
    (re.compile(r"\$[\d,]+\.?\d*"), "<AMOUNT>"),
    (re.compile(r"\b\d+\s*(ms|s|mb|gb|kb|%)\b", re.I), "<METRIC>"),
    (re.compile(r"(port=|:\d)\d{2,5}\b"), "<PORT>"),
    (re.compile(r"\b\d{4,}\b"), "<NUM>"),
]

def extract_template(message: str) -> str:
    template = message
    for pattern, replacement in PATTERNS:
        template = pattern.sub(replacement, template)
    template = re.sub(r"\s+", " ", template).strip()
    return template

class LogPreprocessor:
    def __init__(self, max_features: int = 384):
        self.max_features = max_features
        self.vectorizer = TfidfVectorizer(
            max_features=max_features,
            ngram_range=(1, 2),
            min_df=2,
            sublinear_tf=True,
            token_pattern=r"\b[a-zA-Z_<>][a-zA-Z0-9_<>]*\b",
        )
        self.is_fitted = False

    def preprocess_messages(self, messages: list[str]) -> list[str]:
        return [extract_template(msg) for msg in messages]

    def fit_transform(self, messages: list[str]):
        templates = self.preprocess_messages(messages)
        logger.info(f"Fitting TF-IDF on {len(templates)} templates")
        vectors = self.vectorizer.fit_transform(templates)
        self.is_fitted = True
        dense = vectors.toarray().astype(np.float32)
        logger.info(f"Vectors shape: {dense.shape}")
        return dense, templates

    def transform(self, messages: list[str]):
        if not self.is_fitted:
            raise RuntimeError("Call fit_transform first")
        templates = self.preprocess_messages(messages)
        vectors = self.vectorizer.transform(templates)
        return vectors.toarray().astype(np.float32), templates
