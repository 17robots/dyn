`move FROM TO`. Copies the file FROM to TO (streaming), then removes FROM.
FROM must never be removed unless TO was completely written and closed. If
anything fails, print one failure message, exit with status 1, and do not
leave a partly written TO behind. On success print nothing and exit 0.
