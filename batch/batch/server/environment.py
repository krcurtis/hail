import os
import uuid

from ..log import log

REFRESH_INTERVAL_IN_SECONDS = int(os.environ.get('REFRESH_INTERVAL_IN_SECONDS', 5 * 60))

POD_NAMESPACE = os.environ.get('POD_NAMESPACE', 'batch-pods')

log.info(f'REFRESH_INTERVAL_IN_SECONDS {REFRESH_INTERVAL_IN_SECONDS}')

INSTANCE_ID = uuid.uuid4().hex
log.info(f'INSTANCE_ID = {INSTANCE_ID}')
