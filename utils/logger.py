import logging
import os
import sys

from loguru import logger
from opentelemetry import _logs
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import get_current_span


class OTELink:
    """
    A sink for Loguru that sends logs to OpenTelemetry.
    """

    def __init__(self):
        # Initialize OTEL Logger Provider
        resource = Resource.create(
            {
                "service.name": "resistine-desktop",
                "service.version": "1.0.0",
            }
        )

        self.logger_provider = LoggerProvider(resource=resource)
        _logs.set_logger_provider(self.logger_provider)

        # Add OTLP Exporter if endpoint is configured, else Console
        otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        if otlp_endpoint:
            exporter = OTLPLogExporter(endpoint=f"{otlp_endpoint}/v1/logs")
            self.logger_provider.add_log_record_processor(
                BatchLogRecordProcessor(exporter)
            )
        else:
            # Fallback to console for debugging if OTEL is requested but no endpoint
            # In production, we might want to disable this if not configured.
            pass

        self.otel_logger = self.logger_provider.get_logger("resistine.logger")

    def __call__(self, message):
        record = message.record

        # Map Loguru level to OTEL Severity Number
        level_map = {
            "TRACE": 1,
            "DEBUG": 5,
            "INFO": 9,
            "SUCCESS": 10,
            "WARNING": 13,
            "ERROR": 17,
            "CRITICAL": 21,
        }

        severity_number = level_map.get(record["level"].name, 9)

        # Get trace context if available
        span = get_current_span()
        span_context = span.get_span_context()

        attributes = {
            "filename": record["file"].name,
            "line": record["line"],
            "function": record["function"],
            "module": record["module"],
            "process.id": record["process"].id,
            "thread.id": record["thread"].id,
        }

        # Add extra attributes from Loguru's 'extra' dict
        if record["extra"]:
            attributes.update(record["extra"])

        # Emit to OTEL
        log_record = _logs.LogRecord(
            timestamp=int(record["time"].timestamp() * 1e9),
            observed_timestamp=int(record["time"].timestamp() * 1e9),
            trace_id=span_context.trace_id if span_context.is_valid else None,
            span_id=span_context.span_id if span_context.is_valid else None,
            trace_flags=span_context.trace_flags if span_context.is_valid else None,
            severity_text=record["level"].name,
            severity_number=severity_number,
            body=record["message"],
            attributes=attributes,
        )

        self.otel_logger.emit(log_record)


class InterceptHandler(logging.Handler):
    """
    Default handler from Loguru docs to intercept standard logging messages
    and redirect them to Loguru.
    """

    def emit(self, record):
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_logging(level="INFO", log_to_file=True):
    """
    Configures Loguru to intercept standard logging and adds OTEL sink.
    """
    # Remove default Loguru handler
    logger.remove()

    # On Windows the default console encoding is cp1252 which cannot encode
    # emoji characters used in log messages. Force UTF-8 with replacement
    # so log calls never raise UnicodeEncodeError.
    import platform as _plat
    if _plat.system() == "Windows":
        import io as _io
        for _attr in ("stdout", "stderr"):
            _stream = getattr(sys, _attr, None)
            if _stream is None:
                continue
            if getattr(_stream, "encoding", "utf-8").lower() == "utf-8":
                continue
            # Wrap the raw buffer — more reliable than reconfigure on Windows
            if hasattr(_stream, "buffer"):
                try:
                    _wrapped = _io.TextIOWrapper(
                        _stream.buffer, encoding="utf-8", errors="replace", line_buffering=True
                    )
                    setattr(sys, _attr, _wrapped)
                    continue
                except Exception:
                    pass
            # Fallback: reconfigure in-place
            if hasattr(_stream, "reconfigure"):
                try:
                    _stream.reconfigure(encoding="utf-8", errors="replace")
                except Exception:
                    pass

    # In PyInstaller windowed builds, stdout/stderr can be None.
    console_sink = sys.stdout if getattr(sys, "stdout", None) is not None else getattr(sys, "stderr", None)
    if console_sink is not None and hasattr(console_sink, "write"):
        try:
            colorize = bool(console_sink.isatty())
        except Exception:
            colorize = False

        logger.add(
            console_sink,
            level=level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
            colorize=colorize,
        )

    # Add file sink
    if log_to_file:
        from utils.settings import get_config_dir

        log_dir = os.path.join(get_config_dir(), "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "resistine.log")
        logger.add(
            log_file,
            level=level,
            rotation="10 MB",
            retention="1 week",
            compression="zip",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        )

    # Add OpenTelemetry sink
    try:
        otel_sink = OTELink()
        logger.add(otel_sink, level=level)
    except Exception as e:
        logger.warning(f"Failed to initialize OpenTelemetry sink: {e}")

    # Intercept standard logging calls
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    # Silence some noisy loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)


# Export the logger for convenience
__all__ = ["logger", "setup_logging"]
