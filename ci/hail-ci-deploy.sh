#!/bin/bash
set -ex

source activate hail-ci

gcloud -q auth activate-service-account \
  --key-file=/secrets/gcr-push-service-account-key.json

gcloud -q auth configure-docker

make deploy
