def csv_bytes(rows, header="subject,arm,pre_value,value"):
    body = "\n".join(rows)
    return (header + "\n" + body + "\n").encode("utf-8")
