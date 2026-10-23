import json
import logging
import sys


class GoogleCloudJsonFormatter(logging.Formatter):
    """
    Formata logs em JSON estruturado com chave 'severity' e 'message'
    compatíveis nativamente com a ingestão do Google Cloud Logging.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "timestamp": self.formatTime(record, self.datefmt),
        }
        if hasattr(record, "trace_id"):
            log_entry["logging.googleapis.com/trace"] = record.trace_id
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging(log_level: str = "INFO", use_stderr: bool = False) -> None:
    """
    Configura o logger raiz.
    Quando executado em modo stdio MCP, envia logs para stderr para não corromper stdout.
    Em Cloud Run (StreamableHTTP), envia JSON estruturado para stdout.
    """
    stream = sys.stderr if use_stderr else sys.stdout
    handler = logging.StreamHandler(stream)
    handler.setFormatter(GoogleCloudJsonFormatter())
    logging.root.handlers = [handler]
    logging.root.setLevel(log_level.upper())
