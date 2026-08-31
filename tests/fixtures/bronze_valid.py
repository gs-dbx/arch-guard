import dlt
from pyspark.sql import functions as F


@dlt.table(
    name="raw_events",
    schema="bronze",
    table_properties={"owner": "platform", "cost_center": "eng"},
)
@dlt.expect_or_drop("has_id", "event_id IS NOT NULL")
def raw_events():
    return dlt.read_stream("kafka_events")


@dlt.table(
    name="raw_users",
    schema="bronze",
    table_properties={"owner": "platform", "cost_center": "eng"},
)
@dlt.expect_or_drop("has_user_id", "user_id IS NOT NULL")
def raw_users():
    return dlt.read_stream("s3_landing_zone")
