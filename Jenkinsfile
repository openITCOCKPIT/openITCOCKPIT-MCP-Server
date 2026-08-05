pipeline {
    environment {
        dockerImage = 'openitcockpit/mcp-server'
      }
    agent any
    stages {
        stage('Multi-arch buildx') {
            steps {
                sh '''
                    if ! docker buildx inspect oitc-mcp-multiarch > /dev/null 2>&1; then
                        echo "Buildx-Instanz existiert nicht. Erstelle neu..."
                        docker buildx create --name oitc-mcp-multiarch --use --bootstrap
                    else
                        echo "Buildx-Instanz existiert bereits. Aktiviere..."
                        docker buildx use oitc-mcp-multiarch
                    fi
                '''
                sh 'docker image prune --filter label=stage=build-mcp-intermediate -f'
            }
        }
        stage('Build and Push') {
            environment {
                VERSION = sh(
                    returnStdout: true,
                    script: 'cat VERSION'
                ).trim()
            }
            steps {
                sh '''
                docker buildx build --push --platform linux/amd64,linux/arm64 -f Dockerfile --tag ${dockerImage}:${VERSION} --tag ${dockerImage}:latest  .
                '''
                sh 'docker image prune --filter label=stage=build-mcp-intermediate -f'
            }
        }
    }
}
