import threading
import uuid

import kubernetes as kube
import requests

from ..kubernetes import v1
from ..log import log

from .environment import POD_NAMESPACE, INSTANCE_ID
from .globals import pod_name_job, job_id_job, next_id, _log_path, _read_file, batch_id_batch


class Job:
    @staticmethod
    def pod_exit_code(pod):
        return pod.status.container_statuses[0].state.terminated.exit_code

    def _create_pod(self):
        assert not self._pod_name

        pod = v1.create_namespaced_pod(POD_NAMESPACE, self.pod_template)
        self._pod_name = pod.metadata.name
        pod_name_job[self._pod_name] = self

        log.info('created pod name: {} for job {}'.format(self._pod_name, self.id))

    def _delete_pod(self):
        if self._pod_name:
            try:
                v1.delete_namespaced_pod(
                    self._pod_name, POD_NAMESPACE, kube.client.V1DeleteOptions())
            except kube.client.rest.ApiException as exc:
                if exc.status == 404:
                    pass
                else:
                    raise
            del pod_name_job[self._pod_name]
            self._pod_name = None

    def _read_log(self):
        if self._state == 'Created':
            if self._pod_name:
                try:
                    return v1.read_namespaced_pod_log(self._pod_name, POD_NAMESPACE)
                except kube.client.rest.ApiException:
                    pass
            return None
        if self._state == 'Complete':
            return _read_file(_log_path(self.id))
        assert self._state == 'Cancelled'
        return None

    def __init__(self, pod_spec, batch_id, attributes, callback, dag=None):
        self.id = next_id()
        job_id_job[self.id] = self
        self.dag = dag
        if self.dag:
            self.dag.link_job(self)

        self.batch_id = batch_id
        if batch_id:
            batch = batch_id_batch[batch_id]
            batch.jobs.append(self)

        self.attributes = attributes
        self.callback = callback

        self.pod_template = kube.client.V1Pod(
            metadata=kube.client.V1ObjectMeta(generate_name='job-{}-'.format(self.id),
                                              labels={
                                                  'app': 'batch-job',
                                                  'hail.is/batch-instance': INSTANCE_ID,
                                                  'uuid': uuid.uuid4().hex
                                              }),
            spec=pod_spec)

        self._pod_name = None
        self.exit_code = None

        self._state = 'Created'
        log.info('created job {}'.format(self.id))

        self._create_pod()

    def set_state(self, new_state):
        if self._state != new_state:
            log.info('job {} changed state: {} -> {}'.format(
                self.id,
                self._state,
                new_state))
            self._state = new_state

    def cancel(self):
        if self.is_complete():
            return
        self._delete_pod()
        self.set_state('Cancelled')

    def delete(self):
        # remove from structures
        del job_id_job[self.id]
        if self.batch_id:
            batch = batch_id_batch[self.batch_id]
            batch.remove(self)

        self._delete_pod()

    def is_complete(self):
        return self._state == 'Complete' or self._state == 'Cancelled'

    def mark_unscheduled(self):
        if self._pod_name:
            del pod_name_job[self._pod_name]
            self._pod_name = None
        self._create_pod()

    def mark_complete(self, pod):
        self.exit_code = Job.pod_exit_code(pod)

        pod_log = v1.read_namespaced_pod_log(pod.metadata.name, POD_NAMESPACE)
        fname = _log_path(self.id)
        with open(fname, 'w') as f:
            f.write(pod_log)
        log.info(f'wrote log for job {self.id} to {fname}')

        if self._pod_name:
            del pod_name_job[self._pod_name]
            self._pod_name = None

        self.set_state('Complete')

        if self.dag:
            self.dag.mark_complete()

        log.info('job {} complete, exit_code {}'.format(
            self.id, self.exit_code))

        if self.callback:
            def handler(id, callback, json):
                try:
                    requests.post(callback, json=json, timeout=120)
                except requests.exceptions.RequestException as exc:
                    log.warning(f'callback for job {id} failed due to an error, '
                                f'I will not retry. Error: {exc}')

            threading.Thread(target=handler, args=(self.id, self.callback, self.to_json())).start()

    def to_json(self):
        result = {
            'id': self.id,
            'state': self._state
        }
        if self._state == 'Complete':
            result['exit_code'] = self.exit_code
        pod_log = self._read_log()
        if pod_log:
            result['log'] = pod_log
        if self.attributes:
            result['attributes'] = self.attributes
        return result
