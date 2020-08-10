import configparser
from datetime import datetime
import os
from pyspark.sql import SparkSession
from pyspark.sql.functions import udf, col, monotonically_increasing_id
from pyspark.sql.functions import year, month, dayofmonth, hour, weekofyear
from pyspark.sql import types as t


config = configparser.ConfigParser()
config.read('dl.cfg')

os.environ['AWS_ACCESS_KEY_ID']=config['AWS']['AWS_ACCESS_KEY_ID']
os.environ['AWS_SECRET_ACCESS_KEY']=config['AWS']['AWS_SECRET_ACCESS_KEY']

def create_spark_session():
    """Create a Apache Spark session to process the data.
    Keyword arguments:
    * N/A
    Output:
    * spark -- An Apache Spark session.
    """
    spark = SparkSession \
        .builder \
        .config("spark.jars.packages", "org.apache.hadoop:hadoop-aws:2.7.0") \
        .getOrCreate()
    return spark


def process_song_data(spark, input_data, output_data, run_start_time):
    """Load JSON input data (song_data) from input_data path,
        process the data to extract song_table and artists_table, and
        store the queried data to parquet files.
    Keyword arguments:
    * spark         -- reference to Spark session.
    * input_data    -- path to input_data to be processed (song_data)
    * output_data   -- path to location to store the output (parquet files).
    Output:
    * songs_table   -- directory with parquet files
                       stored in output_data path.
    * artists_table -- directory with parquet files
                       stored in output_data path.
    """
    # --- Load song_data


    # get filepath to song data file
    song_data = input_data

    # --- Read song data file

    df_sd = spark.read.json(song_data)
    df_sd.printSchema()

    # --- Create and write songs_table 
    # extract columns to create songs table

    df_sd.createOrReplaceTempView("songs_table_DF")

    songs_table = spark.sql("""
        SELECT song_id, title, artist_id, year, duration
        FROM songs_table_DF
        ORDER BY song_id
    """)


    # --- Write songs table to parquet files partitioned by year and artist
    songs_table_path = output_data + "songs_table.parquet" + "_" + run_start_time

    # --- Write DF to Spark parquet file (partitioned by year and artist_id)
    print("Writing songs_table parquet files to {}...".format(songs_table_path))
    songs_table.write.mode("overwrite").partitionBy("year", "artist_id").parquet(songs_table_path)


    # ---Create and write artists_table 
    # extract columns to create artists table

    df_sd.createOrReplaceTempView("artists_table_DF")
    artists_table = spark.sql("""
        SELECT  artist_id        AS artist_id,
                artist_name      AS name,
                artist_location  AS location,
                artist_latitude  AS latitude,
                artist_longitude AS longitude
        FROM artists_table_DF
        ORDER BY artist_id desc
    """)
    artists_table.printSchema()


    # write artists table to parquet files
    artists_table_path = output_data + "artists_table.parquet" + "_" + run_start_time
    print("Writing artists_table parquet files to {}...".format(artists_table_path))
    songs_table.write.mode("overwrite").parquet(artists_table_path)


    return songs_table, artists_table

def process_log_data(spark, input_data_ld, input_data_sd, output_data, run_start_time):
    """Load JSON input data (log_data) from input_data path,
        process the data to extract users_table, time_table,
        songplays_table, and store the queried data to parquet files.
    Keyword arguments:
    * spark            -- reference to Spark session.
    * input_data       -- path to input_data to be processed (log_data)
    * output_data      -- path to location to store the output
                          (parquet files).
    Output:
    * users_table      -- directory with users_table parquet files
                          stored in output_data path.
    * time_table       -- directory with time_table parquet files
                          stored in output_data path.
    * songplayes_table -- directory with songplays_table parquet files
                          stored in output_data path.
    """
    # --- Load log_data 

    # get filepath to log data file
    log_data = input_data_ld

    # --- read log data file
    print("Reading log_data files from {}...".format(log_data))
    df_ld = spark.read.json(log_data)


    # ---Create and write users_table
    # filter by actions for song plays

    df_ld_filtered = df_ld.filter(df_ld.page == 'NextSong')

    # extract columns for users table
    df_ld_filtered.createOrReplaceTempView("users_table_DF")
    users_table = spark.sql("""
        SELECT  DISTINCT userId    AS user_id,
                         firstName AS first_name,
                         lastName  AS last_name,
                         gender,
                         level
        FROM users_table_DF
        ORDER BY last_name
    """)


    # --- Write users table to parquet files
    users_table_path = output_data + "users_table.parquet" + "_" + run_start_time
    print("Writing users_table parquet files to {}...".format(users_table_path))
    users_table.write.mode("overwrite").parquet(users_table_path)


    # --- Create and write time_table
    # create timestamp column from original timestamp column
    start_tt = datetime.now()
    print("Creating timestamp column...")
    @udf(t.TimestampType())  
    def get_timestamp (ts):
        return datetime.fromtimestamp(ts / 1000.0)

    df_ld_filtered = df_ld_filtered.withColumn("timestamp", get_timestamp("ts"))


    # create datetime column from original timestamp column

    print("Creating datetime column...")
    @udf(t.StringType())    
    def get_datetime(ts):
        return datetime.fromtimestamp(ts / 1000.0).strftime('%Y-%m-%d %H:%M:%S')

    df_ld_filtered = df_ld_filtered.withColumn("datetime", get_datetime("ts"))


    # extract columns to create time table
    df_ld_filtered.createOrReplaceTempView("time_table_DF")
    time_table = spark.sql("""
        SELECT  DISTINCT datetime AS start_time,
                         hour(timestamp) AS hour,
                         day(timestamp)  AS day,
                         weekofyear(timestamp) AS week,
                         month(timestamp) AS month,
                         year(timestamp) AS year,
                         dayofweek(timestamp) AS weekday
        FROM time_table_DF
        ORDER BY start_time
    """)


    # write time table to parquet files partitioned by year and month
    time_table_path = output_data + "time_table.parquet" + "_" + run_start_time
    print("Writing time_table parquet files to {}...".format(time_table_path))
    time_table.write.mode("overwrite").partitionBy("year", "month").parquet(time_table_path)
    


    # --- Create and write songplays_table 
    # read in song data to use for songplays table

    song_data = input_data_sd

    df_sd = spark.read.json(song_data)

    # Join log_data and song_data DFs

    df_ld_sd_joined = df_ld_filtered.join(df_sd, (df_ld_filtered.artist == df_sd.artist_name) & \
                     (df_ld_filtered.song == df_sd.title))


    # extract columns from joined song and log datasets
    # to create songplays table
    print("Extracting columns from joined DF...")
    df_ld_sd_joined = df_ld_sd_joined.withColumn("songplay_id", monotonically_increasing_id())
    df_ld_sd_joined.createOrReplaceTempView("songplays_table_DF")
    songplays_table = spark.sql("""
        SELECT  songplay_id AS songplay_id,
                timestamp   AS start_time,
                userId      AS user_id,
                level       AS level,
                song_id     AS song_id,
                artist_id   AS artist_id,
                sessionId   AS session_id,
                location    AS location,
                userAgent   AS user_agent
        FROM songplays_table_DF
        ORDER BY (user_id, session_id)
    """)



    # write songplays table to parquet files partitioned by year and month
    songplays_table_path = output_data + "songplays_table.parquet" + "_" + run_start_time

    print("Writing songplays_table parquet files to {}...".format(songplays_table_path))
    time_table.write.mode("overwrite").partitionBy("year", "month").parquet(songplays_table_path)


    return users_table, time_table, songplays_table

def query_count_table(spark, table):
    """Query example returning row count of the given table.
    Keyword arguments:
    * spark            -- spark session
    * table            -- table to count
    Output:
    * count            -- count of rows in given table
    """
    return table.count()

def query_songplays(  spark, songs_table, artists_table, users_table, time_table, songplays_table):
    """Query example using all the created tables.
        Provides example set of songplays and who listened them.
    Keyword arguments:
    * spark            -- spark session
    * songs_table      -- songs_table dataframe
    * artists_table    -- artists_table dataframe
    * users_table      -- users_table dataframe
    * time_table       -- time_table dataframe
    * songplays_table  -- songplays_table dataframe
    Output:
    * schema           -- schema of the created dataframe
    * songplays        -- songplays by user (if any)
    """
    df_all_tables_joined = songplays_table.alias('sp')\
        .join(users_table.alias('u'), col('u.user_id') \
                                    == col('sp.user_id'))\
        .join(songs_table.alias('s'), col('s.song_id') \
                                    == col('sp.song_id'))\
        .join(artists_table.alias('a'), col('a.artist_id') \
                                    == col('sp.artist_id'))\
        .join(time_table.alias('t'), col('t.start_time') \
                                    == col('sp.start_time'))\
        .select('sp.songplay_id', 'u.user_id', 's.song_id', 'u.last_name', \
                'sp.start_time', 'a.name', 's.title')\
        .sort('sp.start_time')\
        .limit(20)

    print("\nJoined dataframe schema:")
    df_all_tables_joined.printSchema()
    print("Songplays by users:")
    df_all_tables_joined.show()
    return

def example_query( spark, songs_table, artists_table, users_table, time_table, songplays_table):
    """Query example using all the created tables.
    Keyword arguments:
    * spark            -- spark session
    * songs_table      -- songs_table dataframe
    * artists_table    -- artists_table dataframe
    * users_table      -- users_table dataframe
    * time_table       -- time_table dataframe
    * songplays_table  -- songplays_table dataframe
    Output:
    * schema           -- schema of the created dataframe
    * songplays        -- songplays by user (if any)
    """
    # Query count of rows in the table
    print("Songs_table count: " + str(query_count_table(spark, songs_table)))
    print("Artists_table count: " + str(query_count_table(spark, artists_table)))
    print("Users_table count: " + str(query_count_table(spark, users_table)))
    print("Time_table count: " + str(query_count_table(spark, time_table)))
    print("Songplays_table count: " + str(query_count_table(spark, songplays_table)))
    
    query_songplays(  spark, songs_table, artists_table, users_table, time_table, songplays_table)

def main():
    """Load JSON input data (song_data and log_data) from input_data path,
        process the data to extract songs_table, artists_table,
        users_table, time_table, songplays_table,
        and store the queried data to parquet files to output_data path.
    Keyword arguments:
    * NA
    Output:
    * songs_table      -- directory with songs_table parquet files
                          stored in output_data path.
    * artists_table    -- directory with artists_table parquet files
                          stored in output_data path.
    * users_table      -- directory with users_table parquet files
                          stored in output_data path.
    * time_table       -- directory with time_table parquet files
                          stored in output_data path.
    * songplayes_table -- directory with songplays_table parquet files
                          stored in output_data path.
    """
    start = datetime.now()
    run_start_time = datetime.now().strftime('%Y-%m-%d-%H-%M-%S-%f')
 #   print("\nSTARTED ETL pipeline (to process song_data and log_data) at {}\n".format(start))

    spark = create_spark_session()
    
    # input_data = "s3a://udacity-dend/"
    # output_data = ""

    # Variables to be used in when data is processed from/to S3.
    input_data_sd = config['AWS']['INPUT_DATA_SD']
    input_data_ld = config['AWS']['INPUT_DATA_LD']
    output_data = config['AWS']['OUTPUT_DATA']

    # Use LOCAL input_data + output_data paths.
#     input_data_sd = config['LOCAL']['INPUT_DATA_SD_LOCAL']
#     input_data_ld = config['LOCAL']['INPUT_DATA_LD_LOCAL']
#     output_data   = config['LOCAL']['OUTPUT_DATA_LOCAL']

    # Use AWS input_data + output_data paths.
    songs_table, artists_table = process_song_data( spark, input_data_sd, output_data, run_start_time)
    users_table, time_table, songplays_table = process_log_data(spark, input_data_ld, input_data_sd, output_data, run_start_time)

    print("Running example queries...")
    example_query( spark, songs_table, artists_table, users_table, time_table, songplays_table)

if __name__ == "__main__":
    main()

