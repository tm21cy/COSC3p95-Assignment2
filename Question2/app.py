# OpenTelemetry Packages
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, TraceIdRatioBased # Sampling methodologies
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter # For export to Jaeger
from opentelemetry.sdk.resources import SERVICE_NAME, Resource

# Utility Packages
from random import randint
import flask
from flask import Flask
import time
from concurrent.futures import ThreadPoolExecutor
import zlib # CRC method
import csv # Result outputs for metrics

# State variables
app = Flask(__name__)
file = None # The output file, as a global variable.
file_num = 0 # File number of the randomized selection.
exec_time = 0 # Execution time of the current block.
checksum = 0 # Checksum of the last file for export.

# OpenTelemetry Configuration

# SAMPLING METHOD - CHANGE TO DEMONSTRATE ALWAYSON AND PROBABILITY!
sampler_always_on = True


# Create a named tracer service for the operation, including our choice of whether we use always-on or ratio @ 40%)
provider = TracerProvider(resource=Resource.create({
            SERVICE_NAME: "file-fetch"
        }))
trace.set_tracer_provider(provider)

if sampler_always_on:
    provider.sampler = ALWAYS_ON
else:
    provider.sampler = TraceIdRatioBased(0.3)

# Exports to our Jaeger OTLP endpoint, insecure mode prevents TLS errors
export = OTLPSpanExporter(endpoint="localhost:4317", insecure=True)
trace.get_tracer_provider().add_span_processor(
   BatchSpanProcessor(export)
)

# Initialize our tracer
tracer = trace.get_tracer(__name__)

# System Variables - can be altered to observe behavior
######################
rate_tokens = 10
rate_limit = 60
max_attempts = 3
######################



# Flask domain route, fetches and returns a random file.
@app.route("/")
def fetch_route():
    attempts = 0
    # Error-Retry Advanced Logic
    while attempts < max_attempts:
        try:
            # Store our execution time globally, and initialize the timer
            global exec_time
            metricstart = time.perf_counter()

            with tracer.start_as_current_span("file-fetch") as threadspan:
                threadspan.set_attribute("attempt", attempts)
                with ThreadPoolExecutor() as executor:
                    # Rate Limiter Advanced Logic
                    with tracer.start_as_current_span("rate-limit") as ratespan:
                        # Check to see if we've exceeded our last rate limit bucket reset.
                        # If we have, reset the tokens and the timer.
                        # If we haven't, and we're all out of tokens, sleep until the tokens are refreshed in 5 second intervals.
                        global rate_limit
                        global rate_tokens
                        timestamp = int(time.time())
                        ratespan.set_attribute("rate-limit.check_time", timestamp)

                        if timestamp >= rate_limit:
                            # Refresh timestamp on last timestamp exceeded (time reset).
                            rate_limit = rate_limit + timestamp
                            rate_tokens = 60

                        ratespan.set_attribute("rate-limit.token_count", rate_tokens)

                        if rate_tokens <= 0:
                            # Wait until buckets refresh, if we've exceeded the count before the time.
                            ratespan.set_attribute("rate-limit.exceeded", True)
                            while timestamp < rate_limit:
                                time.sleep(5)
                                timestamp = int(time.time())
                            rate_limit = rate_limit + timestamp
                            rate_tokens = 60
                        else:
                            # Otherwise, just decrement available tokens and move on.
                            ratespan.set_attribute("rate-limit.exceeded", False)
                            rate_tokens -= 1

                    with tracer.start_as_current_span("async-fetch") as fetchspan:
                        # Track the start (and later, end) times of our threaded fetch function.
                        start = time.perf_counter()
                        # Threads out the file fetching & checksum generation into a fork.
                        res = executor.submit(fetch)
                        # Awaits completion (joining back) and receives the result.
                        (file, checksumres) = res.result()
                        end = time.perf_counter()
                        # Append useful data.
                        fetchspan.set_attribute("async-fetch.filepath", file)
                        fetchspan.set_attribute("async-fetch.execution-time", end - start)
                        fetchspan.set_attribute("async-fetch.checksum", checksumres)
            metricend = time.perf_counter()
            # Store our total execution time
            exec_time = metricend - metricstart

            # Debug Logging for Intentional Error Question
            with open("results.csv", 'a') as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow([exec_time, file_num])

            # Return our file as an attachment, named with the checksum for easy access.
            return flask.send_file(file, as_attachment=True, download_name=f'{checksum}')
        except Exception as exception:
            # If we have retries available, use them, otherwise notify & break.
            print(exception)
            if attempts == max_attempts:
                print("Max attempts failed, exiting...")
                break
            else:
                print(f'Error on run {attempts + 1}, retrying...')
                attempts += 1


# Fetches a desired random file from our files folder. Also generates a checksum for later.
def fetch():
    global file_num
    with tracer.start_as_current_span("filesystem-fetch") as asyncspan:
        rand = randint(1, 20)
        file_num = rand
        ## TO FIX THE BUG, COMMENT THIS BRANCH OUT
        if rand >= 15:
            time.sleep(3)
        filename = f'files/file{rand}.txt'
        with open(filename, "ab") as fa:
            # Generates the checksum and appends it to the span.
            crc(fa.name)
            asyncspan.set_attribute("filesystem-fetch.checksum", checksum)
        return filename, checksum


# Simply breaks a file into chunks and generates a spliced checksum for later use.
def crc(file):
    data = 0
    with open(file, 'rb') as fp:
        while True:
            stream = fp.read(2048)
            if not stream:
                break
            data = zlib.crc32(stream, data) # Splice the current and new checksum data together
    global checksum
    checksum = data # Export result to global

if __name__ == "__main__":
    app.run(host='0.0.0.0', port='5001', use_reloader=False)
