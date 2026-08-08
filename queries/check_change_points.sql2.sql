SELECT
    json_extract(je.value, '$.quote') AS quote,
    length(json_extract(je.value, '$.quote')) AS quote_length
FROM document_topic dt
JOIN json_each(dt.change_points) je;
