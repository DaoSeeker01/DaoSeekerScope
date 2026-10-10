fn main() {
    let schema = schemars::schema_for!(daoseeker_scope::Snapshot);
    let mut value = serde_json::to_value(schema).expect("serialize schema");
    value["$id"] =
        serde_json::json!("https://github.com/DaoSeeker01/DaoSeekerScope/schema/snapshot-v1");
    value["properties"]["schema_version"] = serde_json::json!({"type":"integer", "const":1});
    if let Some(definitions) = value
        .get_mut("$defs")
        .and_then(serde_json::Value::as_object_mut)
    {
        for (name, definition) in definitions {
            if name.starts_with("Observed") {
                definition["required"] =
                    serde_json::json!(["value", "availability", "source", "observed_at", "reason"]);
                definition["allOf"] = serde_json::json!([{
                    "if": {"properties": {"availability":{"const":"available"}}, "required":["availability"]},
                    "then": {"properties": {"value":{"not":{"type":"null"}}, "observed_at":{"type":"integer","minimum":0}, "reason":{"type":"null"}}},
                    "else": {"properties": {"value":{"type":"null"}, "observed_at":{"type":"null"}, "reason":{"not":{"type":"null"}}}}
                }]);
                if let Some(variants) = definition
                    .get_mut("properties")
                    .and_then(|properties| properties.get_mut("value"))
                    .and_then(|value| value.get_mut("anyOf"))
                    .and_then(serde_json::Value::as_array_mut)
                {
                    for variant in variants {
                        if variant["type"] == "string" {
                            variant["minLength"] = serde_json::json!(1);
                            variant["maxLength"] = serde_json::json!(4096);
                        }
                        if variant["type"] == "array" {
                            variant["maxItems"] = serde_json::json!(1024);
                        }
                    }
                }
            }
        }
    }
    println!("{}", serde_json::to_string_pretty(&value).expect("schema"));
}
