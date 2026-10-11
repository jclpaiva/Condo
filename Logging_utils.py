import sys
import logging
from pathlib import Path

def ativar_logging(nome_script, nivel=logging.INFO):
    """
    Redireciona stdout e stderr para ficheiro de log.
    NÃO escreve nada no ecrã.
    """

    logs_dir = Path(__file__).parent / "logs"
    logs_dir.mkdir(exist_ok=True)

    logger = logging.getLogger(nome_script)
    logger.setLevel(nivel)
    logger.propagate = False

    if not logger.handlers:
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            "%Y-%m-%d %H:%M:%S"
        )

        fh = logging.FileHandler(
            logs_dir / f"{nome_script}.log",
            encoding="utf-8"
        )
        fh.setFormatter(formatter)
        fh.setLevel(nivel)

        logger.addHandler(fh)

    class _Redirect:
        def write(self, msg):
            msg = msg.rstrip()
            if msg:
                logger.info(msg)

        def flush(self):
            pass

    sys.stdout = _Redirect()
    sys.stderr = _Redirect()

    return logger
