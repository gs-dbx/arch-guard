import dlt


@dlt.table(name="raw_events", schema="bronze",
           table_properties={"owner": "platform", "cost_center": "eng"})
def raw_events():
    return dlt.read_stream("kafka_events")


@dlt.table(name="shortcut_report", schema="gold",
           table_properties={"owner": "analytics", "cost_center": "eng"})
def shortcut_report():
    # Deliberately reads from bronze, skipping silver — illegal medallion flow.
    return dlt.read("raw_events")
