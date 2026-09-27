from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS `security_keywords` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `keyword` VARCHAR(64) NOT NULL,
    `keyword_key` VARCHAR(64) NOT NULL UNIQUE,
    `direction` VARCHAR(16) NOT NULL,
    `is_enabled` BOOL NOT NULL,
    `created_at` DATETIME(6) NOT NULL
) CHARACTER SET utf8mb4;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS `security_keywords`;"""


MODELS_STATE = (
    "eJztXWtvo7ga/itVPs2RuqPckzk6Wim9zGzPtM1omtmz2p0VcsBJrHIbDG2j3f73Y3MJYA"
    "zF2UAD9Zc2MX7APK95/d5M/uoYlgZ1/H725eoz3Hb+ffJXxwQGJB+YI6cnHWDbcTttcMFS"
    "97sCGyn3cOs3giV2HaC6pH0FdAxJkwax6iDbRZZJWk1P12mjpZKOyFzHTZ6JfnhQca01dD"
    "fQIQf++JM0I1ODTxBHX+17ZYWgrqUGizR6bb9dcbe233Zluh/9jvRqS0W1dM8w48721t1Y"
    "5q43Ml3auoYmdIAL6eldx6PDp6ML7zS6o2CkcZdgiAmMBlfA093E7S6VuK2jKLfzhXJ3uV"
    "CUjgBBqmVScslQsX/3azqEn/q94WQ4HYyHU9LFH+auZfIcXDomJgD69NwuOs/+ceCCoIfP"
    "cUyq/z9D6/kGOHxeo/4Ms2TILLMRj0XURg0xt/F8qoNcAzwpOjTX7oZ87fWnBVT+Ovt6/s"
    "vs6zvS61/0khZ5AIIn4zY81A+OUb5jfskjo2wA3ohwnMQchufXncIplsfDEiSPh7kc00NZ"
    "im0HrtCTKMkxqpXTudRsLpjMLNE/PItoEZf80bNMX0AVGUDnk80gGba1APo+PEVVzP/Uq4"
    "j3Ap4vLs+vbmbX73rj07HPNP6hIxcmRTDs8nn2MOQseCVojoCvw3K3ISST06ue40DTVXRk"
    "IFfAtuBBX7Y0DkXw6KgtjZhgxzaEmU1h6qO0Ms1waE6BrluPUFNi+zxN7H/v5rd8ZrNIVj"
    "0g1T35+0RHuDKaO/9ZeaZKOTxZekh3kYnf0+v93KlfZ1Cm6JkNTJRFcuF7dzP7jV0Tz6/n"
    "Zz5lFnbXjn8W/wRnOeJB9l6yCWFSMAcXjD/rlbVjebYi5EZmgXtppdDcPhpD8cBqCWEFmv"
    "RWOdSeWZYOgZnjpaeADLVLgqxqxkf+T71z+2w+v07N7bOrBTOjv92cXRKznDFjOCuBpyF3"
    "T9Yz2BqJ37U0lvnAyCbKBrqKBrZZ7u+Ida3nahQOvEUqZdCfjHfahH4pUiR3xGi/ziNYB9"
    "gNaQIcE/KCMOMiAxaRnDkFu7KG53gffWge7QXsLq5uLu8Ws5svqXl/MVtc0iN9v3XLtL4b"
    "Myvs7iQn/7ta/HJCv578Pr+9ZBfdXb/F7x06JuC5lmJajwrQkpxEzVFTSu7wyUbkdHuIO4"
    "2UUj5mKasOpLzvIeU08gBSPrr4HblBbW7q23AGNkTs4cNSKHXP1vaUehoppX4sUuc87P7o"
    "afpudZ/INdGGJVDvH4GjKZkjVt/K65s9ZPQNtgWYYO3LjJJLhxmmNM83wDSh3uFkO6NDp0"
    "XpTjXoJNOdMt3Z2vxQBelO27EekAYdEY6TmBbyPCiThxvk5+EGmTzcEmCoeA4nCZdPchLT"
    "QpJHpbKdo4J05yib7wxLXkRoTkAky+VYFs9lyBxG5aFyg1hGdFSiUkkCj0M49LItE47tIH"
    "Uv4SSAUjgHFw5h13KQy1kvcs32JKS+dHdVJRqHTis9QrTeiJQPxID6yGxK6YDM0dWeKaK2"
    "kwPJSCDHvMlPOadRciaztNI4n+WJ6IUEokY6+03RszIkn091M4OzMiT/FqV+5CH5G/rvEy"
    "2l6nCi8omjp0WB+URFlgzOy+D84SJtR7RHppLQvIyzHVW0QBpdbVt+pdH1FqXeBKPri4NU"
    "mGt0BUdLGF00fAyl0dUuo8sXrYjVtQO0zuw6/NZk27EM2w0eHI7CL9rLyULlbs7i3ZyGrU"
    "M6ir3I5sEl4YWEA3VDrJG9yGagkuhCov2dxqpQFUoSU18ZSufb3UVV3llaUZfxjvN944xn"
    "jLBCbBn0wJnIL2XGYpxMjJVPjEnfN3+iN9MLkr7vW5T6kfu+XyERLnavrXWH4/smjp4W+b"
    "5O0E/RrfWR+b5naP1W3N8P/f5gMOl3B+PpaDiZjKbdnR+cPVTkEJ9dfaLrUeppeNlJjuYA"
    "Twr5ZlgaVZUh9nr+8mBcprKd1T2JyvZxTsW12Dsa0qCqCjyaF/PJ0iqaYGNxNfoS9TgSlS"
    "Tawq1jYpM4DWrRGwEOV6UUMiQ6iVmcnMSls8VKuILxakZfCBCnoe1b+w4fKw5oI4alx3u9"
    "4kt0x7jWze9KwvIN2aVYE8WH36MITc22wnWrLMVJTOsoriy55Fr30BQpMM/g5M6TjK0R54"
    "OE6eViJcWZKn76MmBxdlmYJDYzd4P0mvi8ZXGS2qxawLzYdXFmGXOD1jLJyWTgyOkhMMQz"
    "cDFOvsVQIAWHXeB6mFCpcZzpXB3BoKSGYGnVyX2b6lYxRDRvGiRJZUmFjmM5igExBmvObF"
    "3ApxxiM8AWeBVFqcHL3xYp9ZCpU99lBq/nt5+i7mzxOo98y0FrZAo5cwyuBdQzYbcy2Y9e"
    "fvajl8l+eHawmCn7Kec8uFQorELZMeVPUhGNkkW2YF7XrVKQTesHHKKWRRRKGtUC2tPqZD"
    "gqoU6Go1x1Qg+laV4BpBOHznrgBToLzWoGKQ1rAcN6A7Div2BdkPMUTjLe2mrCWlNWzSwr"
    "yysmrKqsjP1VhaWlccqtz0Lw3IQLi/z5ConfRgWSnTqZCrNZ9GA3K4X/HD0wUWsnUeC3Vy"
    "FeQERhNd6Oq1IleYHOLFeY1/nujQdg+t2bDLtj8nk5HpC/o+nkuzcajEakvQ9V8nk5mtL2"
    "AfzurVZd0vKhO1mR9t5Qo+2Q9BytNIrq98jf6XRM+o+GU9JzAjXSc7oEPdKzP17SK6or+n"
    "kKSJ8P/Yl//gm9+nJEe65In+lKW9LzT0fR1Qfdrv/MJWXUwOHLgseGFjwGijB8zkQcpAyw"
    "BYZ63f5RxCG2yTiEAl5ZpKRfmP7k6iKqhbLYw0Rf3ohK+kcWHleCWfFF9psvwCtyo8Dk7k"
    "PkbhNolNzyzDfS7IDH3ZrLmbSEBnLzMPC4zmd357OLy87zAXdmWD5dWSuQthebfqTHkW3D"
    "eCsmiXzvU/NqxJLDEmCYgbXAiEgT3R+VSd6QXrlU+8eYejzoGAhjMjCht2wxsFd41dYff7"
    "6C6VbJS7UQVsK3hQlGX9NAGX5tbfi13i0w7Yq/ys3cbZZ6xNE/2MydmB4YOpxVMIqhf/z8"
    "cvT8G4ZN/MWcwph5VTvd76Dq0d+R+Ay3j5aTdllyupwWeVk47Ex3f9Le0uNql8d1H0+Csi"
    "5BAtLCX7Y6vOcV8iX6A2IMTLq4L7u4yIGqsIObBNXo3i4twkItRB++PFH+goz0rY5IfzfT"
    "yq67tkXUkNxiFxp30HUD7rNmZKpDsRHpd1Vw0FeakK0zIQXtGmnPlLJnHoDucdIh+QHkHa"
    "D+0HH1fnRtoWMZ0GrbUnuAgFaVS60f3+KssFHcK39hBZqBTLmetms9pRFT0UR4EiNX1hdX"
    "1g3A/ovHAcai0S8OtIVRsP6ozCYk0qsgLZ7ZhiTfri2DBkcz3ZtpyciE7FuUep79mqpVJg"
    "pU7EWjCUR9G8OP3C7LeARpgrPsfrQciNbmZ7gtW0UcnqZh5JauII4nVYnS4dpcrBl0kLrp"
    "cJys8MhpoZsV95FuVpMe59MCN+sBOlgwV5iASJu/nM1PHyoBhsPuLWS31+2WScN2u/l52C"
    "7nx85MF/JerZofI05AZJRYMEr8qvHC5/8DBkOkGw=="
)
