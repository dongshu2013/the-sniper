CREATE TABLE IF NOT EXISTS character_tweets (
    id SERIAL PRIMARY KEY,
    character VARCHAR(50) NOT NULL,
    posted_at BIGINT NOT NULL,
    tweet_text TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create an index on character and posted_at for faster lookups
CREATE INDEX IF NOT EXISTS idx_character_tweets_char_posted
ON character_tweets(character, posted_at);
