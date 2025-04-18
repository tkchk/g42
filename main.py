import os
from flask import Flask, request, jsonify
from elasticsearch import Elasticsearch, AuthenticationException
from elastic_transport import TlsError
from elasticsearch.exceptions import NotFoundError

app = Flask(__name__)

def check_es_env():
    es_host = os.getenv("ES_HOST")
    es_api_key = os.getenv("ES_API_KEY")
    es_username = os.getenv("ES_USERNAME")
    es_password = os.getenv("ES_PASSWORD")

    if not es_host:
        print("ERROR: Missing ES_HOST (Elasticsearch endpoint is required)")
        exit(1)

    if es_api_key:
        print("INFO: Will use ES_API_KEY to connect to elasticsearch")
        return True

    if es_username and es_password:
        print("INFO: Will use ES_USERNAME and ES_PASSWORD to connect to elasticsearch")
        return True

    print("ERROR: Missing credentials. Provide either ES_API_KEY or both ES_USERNAME and ES_PASSWORD")
    exit(1)

def create_es_client():
    es_host = os.getenv("ES_HOST")
    es_api_key = os.getenv("ES_API_KEY")
    es_username = os.getenv("ES_USERNAME")
    es_password = os.getenv("ES_PASSWORD")
    verify_certs = bool(int(os.getenv("ES_VERIFY_CERTS", "1")))

    if es_username and es_password:
        try:
            es = Elasticsearch(
                es_host,
                basic_auth=(es_username, es_password),
                verify_certs=verify_certs,
                ssl_show_warn=False
            )
            es.info()
            return es
        except AuthenticationException:
            print("ERROR: Basic authentication failed")
            exit(1)
        except TlsError:
            print("ERROR: Elasticsearch certificate verify failed. Use ES_VERIFY_CERTS=0 to override")
            exit(1)

    # Fallback to API key
    es = Elasticsearch(
        es_host,
        api_key=es_api_key,
        verify_certs=verify_certs,
        ssl_show_warn=False
    )

    try:
        es.info()
    except AuthenticationException:
        print("ERROR: API key authentication failed")
        exit(1)
    except TlsError:
        print("ERROR: Elasticsearch certificate verify failed. Use ES_VERIFY_CERTS=0 in environment to override")
        exit(1)

    return es

@app.route("/population", methods=["GET"])
def get_population():
    city_name = request.args.get("city")
    index = request.args.get("index", "cities")

    if not city_name:
        return jsonify({"error": "Missing 'city' query parameter"}), 400

    try:
        query = {
            "query": {
                "match": {
                    "city": city_name
                }
            }
        }

        res = es.search(index=index, body=query)
        hits_obj = res.get("hits", {})
        hits = hits_obj.get("hits", [])
        total = hits_obj.get("total", {}).get("value", len(hits))  # 2nd parameter is default, uses len(hits) as a fallback mechanism

        if hits:
            results = [
                {
                    "city": hit["_source"].get("city"),
                    "population": hit["_source"].get("population", "Unknown")  # Unknown is the default value
                }
                for hit in hits
            ]
            return jsonify({"results": results})
        else:
            return jsonify({"error": f"City '{city_name}' not found"}), 404

    except NotFoundError:
        return jsonify({"error": f"Index '{index}' not found"}), 404

@app.route("/update", methods=["POST"])
def update_or_add_population():
    if not request.is_json:
        return jsonify({"error": "Request content-type must be application/json"}), 400

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON payload"}), 400

    city_name = data.get("city")
    population = data.get("population")
    index = data.get("index", "cities")

    if not all([city_name, population]):
        return jsonify({"error": "'city' and 'population' fields are required"}), 400

    try:
        query = {
            "query": {
                "match": {
                    "city": city_name
                }
            }
        }

        res = es.search(index=index, query=query["query"])
        hits = res.get("hits", {}).get("hits", [])

        if len(hits) > 1:
            return jsonify({"error": f"Multiple records found for city '{city_name}'. Update operation requires a unique match"}), 400
        elif len(hits) == 1:
            doc_id = hits[0]["_id"]
            es.update(index=index, id=doc_id, doc={"population": population})
            return jsonify({"message": f"Population updated for city '{city_name}' with {population}"}), 200
        else:
            new_doc = {"city": city_name, "population": population}
            es.index(index=index, document=new_doc)
            return jsonify({"message": f"City '{city_name}' added with population {population}"}), 201

    except NotFoundError:
        return jsonify({"error": f"Index '{index}' not found"}), 404

@app.route("/health", methods=["GET"])
def health():
    return "OK", 200


if __name__ == "__main__":
    check_es_env()
    es = create_es_client()
    app.run(
        host=os.getenv("FLASK_RUN_HOST", "0.0.0.0"),
        port=int(os.getenv("FLASK_RUN_PORT", "5000")), 
        debug=False
    )
