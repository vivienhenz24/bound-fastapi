set dotenv-load := false

region := "us-east-1"
account_id := "145023110003"
repo := "bound-fastapi"
tag := "latest"
image_uri := "{{account_id}}.dkr.ecr.{{region}}.amazonaws.com/{{repo}}:{{tag}}"

buildx-setup:
  docker buildx create --use --name multiarch || docker buildx use multiarch

ecr-login:
  aws ecr get-login-password --region {{region}} | docker login --username AWS --password-stdin {{account_id}}.dkr.ecr.{{region}}.amazonaws.com

docker-build:
  docker build -t {{repo}}:{{tag}} .

docker-push: ecr-login
  docker tag {{repo}}:{{tag}} {{image_uri}}
  docker push {{image_uri}}

docker-buildx-push: buildx-setup ecr-login
  docker buildx build --platform linux/amd64,linux/arm64 -t {{image_uri}} --push .
