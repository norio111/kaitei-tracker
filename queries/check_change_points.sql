SELECT
    dt.document_id,
    rd.title,
    je.value ->> 'type' AS type,
    je.value ->> 'point' AS point,
    je.value ->> 'quote' AS quote,
    je.value ->> 'page' AS page
FROM document_topic dt
JOIN revision_document rd ON rd.id = dt.document_id
JOIN json_each(dt.change_points) je
ORDER BY dt.document_id, page;