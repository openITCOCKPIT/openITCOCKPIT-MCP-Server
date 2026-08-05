pipeline {
    environment {
        dockerImage = 'openitcockpit/mcp-server'
      }
    agent any
    stages {
        stage('Build and Publish') {
            environment {
                OPENITCOCKPIT_VERSION = sh(
                    returnStdout: true,
                    script: 'cat VERSION'
                ).trim()
            }
            parallel {
                stage('arm64') {
                    agent {
                        label 'linux-arm64'
                    }
                    steps {
                        sh script: "docker build -f Dockerfile --tag ${dockerImage}:${OPENITCOCKPIT_VERSION}-arm64 ."
                        sh script: "docker push ${dockerImage}:${OPENITCOCKPIT_VERSION}-arm64"
                    }
                }
                stage('amd64') {
                    agent {
                        label 'rhel8-amd64'
                    }
                    steps {
                        sh script: "docker build -f Dockerfile --tag ${dockerImage}:${OPENITCOCKPIT_VERSION}-amd64 ."
                        sh script: "docker push ${dockerImage}:${OPENITCOCKPIT_VERSION}-amd64"
                    }
                }
            }
        }

        stage('Merge architectures') {
            agent {
                label 'rhel8-amd64'
            }
            environment {
                OPENITCOCKPIT_VERSION = sh(
                    returnStdout: true,
                    script: 'cat VERSION'
                ).trim()
            }
            steps {
                sh "docker buildx imagetools create -t ${dockerImage}:${OPENITCOCKPIT_VERSION}  -t ${dockerImage}:latest ${dockerImage}:${OPENITCOCKPIT_VERSION}-amd64 ${dockerImage}:${OPENITCOCKPIT_VERSION}-arm64"
            }
         }
    }
}
