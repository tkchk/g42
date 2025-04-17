# Setting up Elasticsearch
Add helm repository and install elasticsearch to the elasticsearch namespace of your cluster.
```
helm repo add elastic https://helm.elastic.co
helm upgrade -i -n elasticsearch elasticsearch elastic/elasticsearch
```
After deploying the chart, helm will tell you how to extract elastic's user password from kubernete's secret. **Please, do that because we will need it later.**
Don't forget that this chart will spawn 3 replicas of elasticsearch and will require you to have 3 PVC with 30Gi of storage each.
This requirement must be satisfied with corresponding PVs.
```
NAME                                                                STATUS   VOLUME                CAPACITY   ACCESS MODES   STORAGECLASS   VOLUMEATTRIBUTESCLASS   AGE
persistentvolumeclaim/elasticsearch-master-elasticsearch-master-0   Bound    elastic-master-0-pv   30Gi       RWO                           <unset>                 33h
persistentvolumeclaim/elasticsearch-master-elasticsearch-master-1   Bound    elastic-master-1-pv   30Gi       RWO                           <unset>                 33h
persistentvolumeclaim/elasticsearch-master-elasticsearch-master-2   Bound    elastic-master-2-pv   30Gi       RWO                           <unset>                 33h
```

In order to import cities dataset from your PC, we're going to expose elasticsearch service on some random 30k+ port via NodePort type like this.
```
kubectl -n elasticsearch patch svc elasticsearch-master -n elasticsearch -p '{"spec": {"type": "NodePort"}}'
kubectl get svc
NAME                            TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)                         AGE
elasticsearch-master            NodePort    10.109.48.132   <none>        9200:30968/TCP,9300:32276/TCP   36h
elasticsearch-master-headless   ClusterIP   None            <none>        9200/TCP,9300/TCP               36h
```
Now we can use the hostname of our node to reference it. Port `30968` is just what we need. Before starting the import, please make sure that elasticsearch is available and cluster status shows green. This can be done by simple curl request to the cluster health endpoint. Also, note that by default, elasticsearch uses self-signed certificate for all incomming connections, that's why we use `-k` option with curl here to force the trust.
```
curl -k -s -u "elastic:${ELASTIC_USER_PASSWORD}" https://kube2.local:30968/_cluster/health | jq
{
  "cluster_name": "elasticsearch",
  "status": "green",
  "timed_out": false,
  "number_of_nodes": 3,
  "number_of_data_nodes": 3,
  "active_primary_shards": 1,
  "active_shards": 2,
  "relocating_shards": 0,
  "initializing_shards": 0,
  "unassigned_shards": 0,
  "delayed_unassigned_shards": 0,
  "number_of_pending_tasks": 0,
  "number_of_in_flight_fetch": 0,
  "task_max_waiting_in_queue_millis": 0,
  "active_shards_percent_as_number": 100.0
}
```
## Importing the dump
Next, run this curl command to actually import the dataset to elasticsearch. We will use index name `cities` by default. It's hardcoded in the dump.
```
curl -k -X POST -u "elastic:${ELASTIC_USER_PASSWORD}" 'https://kube2.local:30968/_bulk?pretty' -H "Content-Type: application/json" --data-binary @db/city-data.ndjson
```
You should recieve a giant output from elastic in JSON format with 201 status codes. If you have it, the import was successful. Should be around 47k records in total.
```
...
    {
      "index" : {
        "_index" : "cities",
        "_id" : "yD3hQpYBRF_dJjTK6wwk",
        "_version" : 1,
        "result" : "created",
        "_shards" : {
          "total" : 2,
          "successful" : 2,
          "failed" : 0
        },
        "_seq_no" : 47867,
        "_primary_term" : 1,
        "status" : 201
      }
...
```
After we've finished with the import, the service can (and should) be switched back to ClusterIP like this.
```
kubectl -n elasticsearch patch svc elasticsearch-master -n elasticsearch -p '{"spec": {"type": "ClusterIP"}}'
```
## Caveats
1. We could have used some more specific elasticsearch import tools, but they require installing additional dependencies (npm for instance). Curl is much easier and compatible, although it may seem verbose.
2. The actual data from elasticsearch is represented in JSON format, but the dump is modified so it can be compatible with elasticsearch's /_bulk API. It's not an exact JSON.
3. Now we can use `elasticsearch-master.elasticsearch.svc.cluster.local` with port `9200` to access our elasticsearch installation from within our kubernetes cluster, and all the requests to it will be ballanced between pods.
4. If you're using self-hosted kubernetes like i did, You should spread PVs for elastic cluster evenly between nodes. That way, pods will also spread evenly on the nodes of your cluster. This can be achieved by specifying `nodeAffinity` block in the PV manifest. And, that block should bind the PV to a specific node using node labels.

# Deploying the app
In order to build the application, docker is pretty much enough.
```
docker build . -t some-registry.local/g42/assignment
```
The image itself must be pushed to some docker registry. If it requires login, do that before pushing.
```
docker login some-registry.local
docker push some-registry.local/g42/assignment
```
## Creating the namespace
As easy as it goes
```
kubectl create namespace g42
```
## Preparing helm chart
Before using helm chart, replace `image-repo` with a reference to the image you've pushed inside of `values.yaml`.
Or, as an option, you can use a pre-built image I made - just use `alexm8/g42`.
```
sed -i 's/image-repo/alexm8\/g42/g' g42-population/values.yaml
```
If your registry uses credentials, you also have to create a secret in kubernetes, so it can fetch the image from there. Also, the registry is required to use SSL, otherwise, kubernetes (specifically containerd) will refuse to download the image. The name `regcred` is hardcoded in the chart, so don't change it to something else.
```
kubectl -n g42 create secret docker-registry regcred --docker-server=<your-registry-server> --docker-username=<your-name> --docker-password=<your-pword> --docker-email=<your-email>
```
## Configuring database
Now, create 2 secrets in kubernetes. One for elasticsearch user, and one for the password. Use that password helm told you about before while setting up the database.
```
kubectl -n g42 create secret generic el-user --from-literal=ES_USERNAME=elastic
kubectl -n g42 create secret generic el-password --from-literal=ES_PASSWORD=supersecret123
```
You can also use API key from elasticsearch. In such case, the application will ignore missing credentials, and use API key.
```
kubectl -n g42 create secret generic el-apikey --from-literal=ES_API_KEY=<your-api-key>
```
You need to specify elasticsearch host at the helm's `values.yaml` level. Since it's not a sensitive information, you won't mess with kubernetes secrets here. Just look for elasticsearch key and replace the `host` value. Also, set 1 or 0 whether an application should trust elasticsearch's self signed certificate. It's represented as `ES_VERIFY_CERTS` variable inside of the application, and it's True by default. Since, we didn't tell elasticsearch to use a trusted certificate, let's disable this kind of check, or our application will fail.
```
...
elasticsearch:
  host: https://elasticsearch-master.elasticsearch.svc.cluster.local:9200
  verifySSL: 0
...
```
Everything will be injected in the environment of running application's pod. This is secure enough, but if we need more, there are plenty solutions for storing secrets in a centralised way.
## Deploying the application
Just issue a helm upgrade command with install (-i) option.
```
helm upgrade -i -n g42 g42-assignment g42-chart/ --values g42-population/values.yaml
```
And wait for pod to enter the Running state. It's very small and should be up within seconds.
```
kubectl get all
NAME                                                 READY   STATUS    RESTARTS   AGE
pod/g42-assignment-g42-population-797f55c5fd-967rd   1/1     Running   0          157m

NAME                                    TYPE        CLUSTER-IP     EXTERNAL-IP   PORT(S)   AGE
service/g42-assignment-g42-population   ClusterIP   10.106.13.52   <none>        80/TCP    157m

NAME                                            READY   UP-TO-DATE   AVAILABLE   AGE
deployment.apps/g42-assignment-g42-population   1/1     1            1           157m

NAME                                                       DESIRED   CURRENT   READY   AGE
replicaset.apps/g42-assignment-g42-population-797f55c5fd   1         1         1       157m

NAME                         DATA   AGE
configmap/kube-root-ca.crt   1      37h

NAME                                          TYPE                             DATA   AGE
secret/el-password                            Opaque                           1      3h2m
secret/el-user                                Opaque                           1      3h3m
secret/regcred                                kubernetes.io/dockerconfigjson   1      3h13m
secret/sh.helm.release.v1.g42-assignment.v1   helm.sh/release.v1               1      157m

NAME                                                      CLASS   HOSTS       ADDRESS      PORTS   AGE
ingress.networking.k8s.io/g42-assignment-g42-population   nginx   g42.local   10.0.0.251   80      157m
```
## Accessing the application
For an example, I've added an ingress to the helm chart with the hostname `g42.local` in `values.yml`
```
...
ingress:
  enabled: true
  className: "nginx"
  annotations: {}
    # kubernetes.io/ingress.class: nginx
    # kubernetes.io/tls-acme: "true"
  hosts:
    - host: g42.local
      paths:
        - path: /
          pathType: Prefix
...
```
This makes our app accessible over `g42.local` domain name.
## Using the app
A simple `GET` request to `/population` endpoint with `city` parameter will return it's population like this.
```
curl -s 'g42.local/population?city=Kyiv' | jq
{
  "results": [
    {
      "city": "Kyiv",
      "population": 2952301
    }
  ]
}
```
If we find multiple cities, we show that on the output.
```
curl -s 'g42.local/population?city=Moscow' | jq
{
  "results": [
    {
      "city": "Moscow",
      "population": 17332000
    },
    {
      "city": "Moscow",
      "population": 25616
    }
  ]
}
```
The `POST` request to `/update` endpoint serves both for updating the city's population and creating a new city. `Content-Type: application/json` header is mandatory in this case.
```
curl -s -X POST -H "Content-Type: application/json" 'g42.local/update' -d '{"city": "Kyiv", "population": "25"}' | jq
{
  "message": "Population updated for city 'Kyiv' with 25"
}
```
If we match several cities, our update operation is rejected!
```
curl -s -X POST -H "Content-Type: application/json" 'g42.local/update' -d '{"city": "Moscow", "population": "25"}' | jq
{
  "error": "Multiple records found for city 'Moscow'. Update operation requires a unique match"
}
```
If we didn't find a city in the database, it will just create a new one. Subsequent requests for updates will work as expected.
```
curl -s -X POST -H "Content-Type: application/json" 'g42.local/update' -d '{"city": "Wonderworld", "population": "125"}' | jq
{
  "message": "City 'Wonderworld' added with population 125"
}
curl -s -X POST -H "Content-Type: application/json" 'g42.local/update' -d '{"city": "Wonderworld", "population": "126"}' | jq
{
  "message": "Population updated for city 'Wonderworld' with 126"
}
curl -s 'g42.local/population?city=Wonderworld' | jq
{
  "results": [
    {
      "city": "Wonderworld",
      "population": "126"
    }
  ]
}
```
## Caveats
1. The app says this in the log. I'm using Flask framework as the most lightweight python web framework out there. We could wrap the application in gunicorn, but I faced issues with preflight application credentials checks because when you launch it, you are not running python file directly - you're launching gunicorn and specify a Flask object from the code file.
```
WARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.
```
2. Logging for `/health` endpoint could be disabled. It's way too verbose.
3. The codebase itself could be more optimized. Especially when I do credentials checks.
4. The application responses could be more informative, like reporting the amount of cities it found. Also, way more important thing, these responses should have a pre-defined format and always use it (like reporting an empty `error` field when there's no error)
5. Pagination has to be added. It's done by specifying an additional `GET` parameter of `page` and it limits requests to the database based on that. All the backends out there have this feature. It reduces the load on database servers dramatically.
6. Usualy, endpoints for updating or adding a records should be separate, but the assignment specifically said "- an endpoint for inserting or updating a city and its population"