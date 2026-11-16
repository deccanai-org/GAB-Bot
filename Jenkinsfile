// Builds the GAB FAQ Discord bot, pushes it to ECR and deploys it to the
// prod-cluster EKS cluster (namespace gab-bot). Same flow as projectmgmtsvc and
// campaign-module: Deploy / Rollback / Restart, image tag = Jenkins build number.
//
// The bot holds one Discord gateway connection, so it runs as exactly one pod
// with a Recreate rollout. The deployment pins the image by registry digest,
// as k8s-manifests/prod/deployment.yaml expects (its template tag is
// deliberately unusable: release-required).
pipeline {
    agent { label 'backend' }

    parameters {
        string(name: 'BRANCH', defaultValue: 'main', description: 'Branch to build')
        choice(name: 'ENVIRONMENT', choices: ['prod'], description: 'Environment to deploy')
        choice(name: 'ACTION', choices: ['Deploy', 'Rollback', 'Restart'], description: 'Select the action to perform')
        string(name: 'ROLLBACK_VERSION', defaultValue: '', description: 'Image tag (Jenkins build number) to roll back to; only used if ACTION is Rollback')
    }

    environment {
        AWS_REGION = 'ap-south-1'
        ECR_URI = '874846752452.dkr.ecr.ap-south-1.amazonaws.com'
        REPO_NAME = 'gab-bot'
        NAMESPACE = 'gab-bot'
        DEPLOYMENT = "gab-bot-${params.ENVIRONMENT}"
        ECR_REPO = "gab-bot-${params.ENVIRONMENT}"
        MANIFEST_DIR = "k8s-manifests/${params.ENVIRONMENT}"
        DOCKER_BUILDKIT = '1'
    }

    options {
        buildDiscarder(logRotator(numToKeepStr: '20'))
        disableConcurrentBuilds()
        timeout(time: 45, unit: 'MINUTES')
    }

    stages {
        stage('Checkout') {
            steps {
                git credentialsId: 'github-gab-bot', url: 'https://github.com/deccanai-org/GAB-Bot.git', branch: "${params.BRANCH}"
            }
        }

        stage('Building Image') {
            when { expression { params.ACTION == 'Deploy' } }
            steps {
                script {
                    env.IMAGE_TAG = "${env.ECR_REPO}:${env.BUILD_NUMBER}"
                    echo "Building ${env.IMAGE_TAG}"
                    sh 'docker build --platform linux/amd64 -t "$IMAGE_TAG" .'
                }
            }
        }

        stage('Smoke Test Image') {
            when { expression { params.ACTION == 'Deploy' } }
            steps {
                // Same offline check as CI: non-root, read-only filesystem, no network.
                sh '''
                    docker run --rm --read-only --network none \
                      --tmpfs /tmp:rw,size=256m \
                      --tmpfs /app/output:rw,uid=10001,gid=10001,size=64m \
                      --memory 1536m --cpus 1.5 \
                      "$IMAGE_TAG" python scripts/smoke_image.py
                '''
            }
        }

        stage('Pushing to ECR') {
            when { expression { params.ACTION == 'Deploy' } }
            steps {
                script {
                    sh '''
                        aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_URI"
                        docker tag "$IMAGE_TAG" "$ECR_URI/$IMAGE_TAG"
                        docker push "$ECR_URI/$IMAGE_TAG"
                    '''
                    env.IMAGE_DIGEST = sh(
                        script: 'aws ecr describe-images --region "$AWS_REGION" --repository-name "$ECR_REPO" --image-ids imageTag="$BUILD_NUMBER" --query "imageDetails[0].imageDigest" --output text',
                        returnStdout: true
                    ).trim()
                    if (!(env.IMAGE_DIGEST ==~ /sha256:[0-9a-f]{64}/)) {
                        error "Could not read the pushed image digest (got '${env.IMAGE_DIGEST}')"
                    }
                    echo "Pushed ${env.ECR_URI}/${env.IMAGE_TAG} (${env.IMAGE_DIGEST})"
                }
            }
        }

        stage('Deploy to Kubernetes') {
            when { expression { params.ACTION == 'Deploy' } }
            steps {
                script {
                    withProdCluster {
                        sh '''
                            set -e
                            kubectl apply -f "$MANIFEST_DIR/secret.yaml"
                            kubectl apply -f "$MANIFEST_DIR/output-pvc.yaml"
                            sed "s|$ECR_URI/$ECR_REPO:release-required|$ECR_URI/$ECR_REPO@$IMAGE_DIGEST|" "$MANIFEST_DIR/deployment.yaml" > rendered-deployment.yaml
                            grep -q "$ECR_REPO@$IMAGE_DIGEST" rendered-deployment.yaml
                            kubectl apply -f rendered-deployment.yaml
                        '''
                    }
                }
            }
        }

        stage('Monitor Deployment') {
            when { expression { params.ACTION == 'Deploy' } }
            steps {
                script {
                    withProdCluster {
                        // The startup probe allows up to 10 minutes for the gateway,
                        // command sync and FAQ engine to become ready.
                        def status = sh(
                            script: 'kubectl rollout status deployment/"$DEPLOYMENT" -n "$NAMESPACE" --timeout=12m',
                            returnStatus: true
                        )
                        if (status != 0) {
                            sh '''
                                kubectl get pods -n "$NAMESPACE" -l app="$DEPLOYMENT" -o wide || true
                                kubectl logs -n "$NAMESPACE" deployment/"$DEPLOYMENT" --tail=80 || true
                            '''
                            echo "Deployment ${env.DEPLOYMENT} did not become ready. Rolling back..."
                            sh 'kubectl rollout undo deployment/"$DEPLOYMENT" -n "$NAMESPACE"'
                            error "Deployment failed and was rolled back"
                        }
                        echo "Deployment ${env.DEPLOYMENT} is healthy and stable."
                    }
                }
            }
        }

        stage('Rollback') {
            when { expression { params.ACTION == 'Rollback' } }
            steps {
                script {
                    if (!params.ROLLBACK_VERSION?.trim()) {
                        error 'No rollback version specified.'
                    }
                    withProdCluster {
                        sh """
                            kubectl set image deployment/${env.DEPLOYMENT} ${env.DEPLOYMENT}=${env.ECR_URI}/${env.ECR_REPO}:${params.ROLLBACK_VERSION.trim()} -n ${env.NAMESPACE} &&
                            kubectl rollout status deployment/${env.DEPLOYMENT} -n ${env.NAMESPACE} --timeout=12m
                        """
                    }
                }
            }
        }

        stage('Restart') {
            when { expression { params.ACTION == 'Restart' } }
            steps {
                script {
                    withProdCluster {
                        sh '''
                            kubectl rollout restart deployment/"$DEPLOYMENT" -n "$NAMESPACE" &&
                            kubectl rollout status deployment/"$DEPLOYMENT" -n "$NAMESPACE" --timeout=12m
                        '''
                    }
                }
            }
        }
    }

    post {
        always {
            sh 'docker image rm "$IMAGE_TAG" "$ECR_URI/$IMAGE_TAG" >/dev/null 2>&1 || true'
        }
        success {
            echo "Pipeline succeeded: ${params.ACTION} ${env.DEPLOYMENT}"
        }
        failure {
            echo "Pipeline failed: ${params.ACTION} ${env.DEPLOYMENT}"
        }
    }
}

def withProdCluster(Closure body) {
    withKubeConfig(
        caCertificate: '',
        clusterName: 'prod-cluster',
        contextName: 'prod-cluster',
        credentialsId: 'prod-k8s-token',
        namespace: '',
        restrictKubeConfigAccess: false,
        serverUrl: 'https://DBA93E67CDCA7C597468BEFA56D7CA0F.gr7.ap-south-1.eks.amazonaws.com'
    ) {
        body()
    }
}
