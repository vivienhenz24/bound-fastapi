REGION ?= us-east-1
ACCOUNT_ID ?= 145023110003
REPO ?= bound-fastapi
TAG ?= latest
IMAGE_URI ?= $(ACCOUNT_ID).dkr.ecr.$(REGION).amazonaws.com/$(REPO):$(TAG)

.PHONY: buildx-setup ecr-login docker-build docker-push docker-buildx-push

buildx-setup:
	docker buildx create --use --name multiarch || docker buildx use multiarch

ecr-login:
	aws ecr get-login-password --region $(REGION) | docker login --username AWS --password-stdin $(ACCOUNT_ID).dkr.ecr.$(REGION).amazonaws.com

docker-build:
	docker build -t $(REPO):$(TAG) .

docker-push: ecr-login
	docker tag $(REPO):$(TAG) $(IMAGE_URI)
	docker push $(IMAGE_URI)

docker-buildx-push: buildx-setup ecr-login
	docker buildx build --platform linux/amd64,linux/arm64 -t $(IMAGE_URI) --push .
