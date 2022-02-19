SELECT mwpage.page_id, mwpage.page_title, mwtext.old_text, group_concat(mwcategorylinks.cl_to) as category, mwuser.user_email, mwrevision.rev_timestamp
FROM mwrevision, mwtext, mwuser, mwpage
LEFT JOIN mwcategorylinks ON mwcategorylinks.cl_from = mwpage.page_id
WHERE mwpage.page_latest = mwrevision.rev_id
AND mwrevision.rev_text_id = mwtext.old_id
AND mwrevision.rev_user = mwuser.user_id
GROUP BY page_id;