"""body/ — action executor package.

The body is an API gateway. The cortex decides what to do; the body does it.
Each executor handles one action type: internal (journal, gift, shop) or
external (web browse, X post, Telegram send).

Usage from pipeline/body.py:
    from body import dispatch_action
    result = await dispatch_action(action_req, visitor_id, monologue)
"""

from body.executor import dispatch_action  # noqa: F401

# Import executor modules so their @register decorators run.
import body.internal  # noqa: F401
import body.web  # noqa: F401
import body.telegram  # noqa: F401
import body.x_social  # noqa: F401
