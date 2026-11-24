"""Write pairs_0.3.218.eval: the "main" log of tests/inspect_logs.py, written by inspect_ai 0.3.218 (the oldest
version the tests were run on), so the tests also cover a newer inspect_ai reading an older log.

    python tests/fixtures/inspect/make_fixture.py   # in an environment with inspect_ai==0.3.218
"""

import sys
import tempfile
from pathlib import Path

import inspect_ai

HERE = Path(__file__).parent
VERSION = "0.3.218"

if inspect_ai.__version__ != VERSION:
    raise SystemExit(f"needs inspect_ai=={VERSION}, found {inspect_ai.__version__}")
sys.path.insert(0, str(HERE.parent.parent))
import inspect_logs as gen  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp)
    path = gen._named(out, gen._run(out, gen.Task(dataset=gen._samples(), solver=[gen.maybe_raise()],
                                                  scorer=gen.det(), name="pairs"), epochs=gen.EPOCHS), "pairs")
    target = HERE / f"pairs_{VERSION}.eval"
    target.write_bytes(path.read_bytes())
    print("wrote", target.name)
