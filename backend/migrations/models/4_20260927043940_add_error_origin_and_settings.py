from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS `system_settings` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `key` VARCHAR(64) NOT NULL UNIQUE,
    `value` JSON NOT NULL,
    `updated_at` DATETIME(6) NOT NULL
) CHARACTER SET utf8mb4;
        ALTER TABLE `request_logs` ADD `upstream_status_code` INT NOT NULL DEFAULT 0;
        ALTER TABLE `request_logs` ADD `error_origin` VARCHAR(16) NOT NULL DEFAULT '';
        ALTER TABLE `request_logs` ADD `upstream_error` LONGTEXT NOT NULL;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `request_logs` DROP COLUMN `upstream_status_code`;
        ALTER TABLE `request_logs` DROP COLUMN `error_origin`;
        ALTER TABLE `request_logs` DROP COLUMN `upstream_error`;
        DROP TABLE IF EXISTS `system_settings`;"""


MODELS_STATE = (
    "eJztXWtv4zYW/SuBP80C7sDxK2lRLGAnmWl28hiMPbtFi0JgJMYmoteIVBKjm/++pB6WRF"
    "GK6LUUS+GXJCZ5ZOpc6vK+xPzdsxwDmvjj7OvlF7jp/XL0d88GFqR/cD39ox5w3aSdNRBw"
    "ZwZDgYu0B7gJGsEdJh7QCW2/ByaGtMmAWPeQS5Bj01bbN03W6Oh0ILJXSZNvox8+1Iizgm"
    "QNPdrx51+0GdkGfIY4/ug+aPcImkZmsshg3x20a2TjBm2XNvkUDGTfdqfpjulbdjLY3ZC1"
    "Y29HI5uw1hW0oQcIZJcnns+mz2YX3Wl8R+FMkyHhFFMYA94D3ySp273Tkraept3cLrXFxV"
    "LTehIE6Y7NyKVTxcHdr9gUfhoej0/Gp6Pp+JQOCaa5bTl5Cb86ISYEBvTcLHsvQT8gIBwR"
    "cJyQGvzO0Xq2Bp6Y13g8xyydMs9szGMZtXFDwm2ynpog1wLPmgntFVnTj8fD0xIq/z37dv"
    "bb7NsHOuof7Csd+gCET8ZN1DUM+xjfCb/0kdHWAK9lOE5j9sPz2y7hDMvTcQWSp+NCjllX"
    "nmLXg/foWZbkBNXJ5VxpNZcsZp7oH75DtQihP8w80+dQRxYwxWRzSI5tI4R+jC5RF/M/Hd"
    "fEewnP5xdnl9ezqw/H0/40YBr/MBGBaRGMB2KefQwFG14FmmPg27A8aAnJ9PK673nQJpqJ"
    "LEQkbAsR9HVLY18ETw7a0kgI9lxLmtkMpjlKa9MM++YUmKbzBA0tsc+zxP5rcXsjZjaP5N"
    "UD0snRf49MhGujuffrvW/rjMOjOx+ZBNn4I/u+f/aa1xmMKXZlC1Nlkd74PlzPfuf3xLOr"
    "23lAmYPJyguuElxgXiAe5O4kmwimBLN3wQSrXlt5ju9qUm5kHriTVorM7YMxFPeslhDWoM"
    "1uVUDt3HFMCOwCLz0D5Ki9o8i6Vnzs/zS7tue3t1eZtT2/XHIr+vv1/IKa5ZwZI9gJfAOR"
    "HVnPYRskftvSWuZDI5sqG0g0A2zy3C+odW0WahQBvEMqZTQ8mW61CftQpkgW1Gi/KiLYBJ"
    "hENAGBCXlOmSHIgmUk5y7B76zRNT7Gf7SP9hJ2l5fXF4vl7PprZt2fz5YXrGcYtG641g9T"
    "bofdXuToP5fL347Yx6M/bm8u+E13O275R4/NCfjE0WznSQNGmpO4OW7KyB0+u4hebgdxZ5"
    "FKyocsZd2DjPcdpJxF7kHKBxe/ozdo3NrmJlqBLRF79LCUSt13jR2lnkUqqR+K1AUPezB7"
    "lr67f0jlmljDHdAfnoBnaLkeZ+gUjc13WUOLbwE2WAUyY+SyaUYpzbM1sG1o9gTZzrirX5"
    "bu1MNBKt2p0p2dzQ/VkO50PecRGdCT4TiN6SDPoyp5uFFxHm6Uy8PdAQw13xMk4YpJTmM6"
    "SPKkUrZzUpLunOTznVHJiwzNKYhiuRrL8rkMlcOoPVRuUcuIzUpWKmngYQiHfW3HhON6SN"
    "9JOCmgEs7ehUPZdTxEBPtFodmehjSX7q6rRGPfaaUniFZrmfKBBNAcmW0pHVA5usYzRcx2"
    "8iCdCRSYN8Up5yxKrWSeVhbnc3wZvZBCNEjnsC16VoXki6luZ3BWheTfo9QPPCR/zX59Zq"
    "VUPUFUPtXbLwvMpyqyVHBeBef3F2k7oHdkagnNqzjbQUULlNHVte1XGV3vUeptMLq+ekiH"
    "hUZX2FvB6GLhY6iMrm4ZXYFoZayuLaBzZtf+X012PcdySfjgCBR+2bucPFS9zVn+Nqflmp"
    "DNYieyRXBFeCnhQF9Ta2QnsjmoIrqU6OBNY12qCiWNaa4Mpfd9cV6Xd5ZV1FW842LfOOcZ"
    "I6xRWwY9Chbya5mxBKcSY9UTY8r3LV7o7fSClO/7HqV+4L7vN0iFi8mVs+oJfN9Ub7/M9/"
    "XCcZrprA7M952j1Xtxf38eDkejk+FgND2djE9OJqeDrR+c7ypziOeXn9l+lHkaXneS4zUg"
    "kkKxGZZF1WWIvZ2/PJpWqWzndU+qsn1aUHEtd0ZDFlRXgUf7Yj55WmUTbDyuQV+iGUeilk"
    "Rb9OqY3CLOgjp0IsD+qpQihmQXMY9Ti7hytliLdjBRzegrAeIstHt73/5jxSFt1LD0Rccr"
    "vkZ3guvc+q4lLN+StxQbonj/7yhC23CdaN+qSnEa0zmKa0suEecB2jIF5jmcevMkZ2sk+S"
    "BpeoVYRXGuip8dBizPLg9TxObWbphek1+3PE5Rm1cLWBS7Ls8sY2HQWiU5uQwcvTwElnwG"
    "LsGpUwwlUnCYAOJjSqUhcKYLdQSHUhqCp9Wk923rG82S0bxZkCKVJxV6nuNpFsQYrASrdQ"
    "mfC4jNATvgVZSlBi9+X2bUQ65OfZsZvLq9+RwP54vXReQ7HlohW8qZ43AdoJ4Lu1XJfhwX"
    "Zz+Oc9kP3w03M2035VwEVwqFVyhbpoJFKqNR8sgOrOumVQpyWf2AR9WyjELJojpAe1adjC"
    "cV1Ml4UqhOWFeW5nuATOrQOY+iQGepWc0hlWEtfTB7lP2QUS05YAeWeNOaJeYQu3QeUqZi"
    "Hqnol6a/XXWdjSYP21ngV1TWeSgFfk5wt/nSPtbeLy3qoyMOrJrvvZTyqeMD2pdqTE9Lgm"
    "EO1oEdNUv0cFIlBkBHFVId9HFpXehZCGM6ManDGjjYG5zY8Odfb2DH1HI2A8JadOiEfD4i"
    "BVR+k3onSBmP6p2gdyX1mKP/452g1PLA0BPsgvMI9unLN2iCAvMi8gW+Y9jGg9df4vUet6"
    "Z5rMufWmwwgdYCEhJOLedYZQf0yzwsHAzVcDhW+Vrd8rUk/y3CXv8lQqc9rUdg+gIvttju"
    "3wKat/jrV3+NWfzKDlF2SKOhy8AsEeywsblSvLECw0K22k+7tZ8yQ1c2fpnGqJ311Z11DX"
    "Bw7BDA+MnxpN5oE0A7+N+dhpMqJQh0VEk0M1eEoM7WUXG0g1nu7bRkVBztPUq9yH5NS51l"
    "seWOGUghmisLPXC7LOcRZAnOs/vJ8SBa2V/gJiD5ks4I2MKzDLl6hJaRWxSDpM0eeNq6Bu"
    "lFRe+d3jEMN6ez2eJsdn7Re3kbF2sGPaSvewInK+rpl7pZyRjlZrXpce6XuFmP0MOSNQwp"
    "iLL5q9n87KGSYDga3kF2jweDKu+IDAbFL4kMBEcd2wSKDlYojhGnICpKLBklftN44cv/AK"
    "8kPGo="
)
