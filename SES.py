"""Small Amazon SES client used by wellness-log."""

import boto3


class AmazonSES:

    def __init__(
        self,
        region,
        access_key,
        secret_key,
        from_address,
        charset="UTF-8",
        session_token=None,
        client=None,
    ):
        self.region = region
        self.access_key = access_key
        self.secret_key = secret_key
        client_options = {"region_name": self.region}
        if self.access_key and self.secret_key:
            client_options.update(
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
            )
            if session_token:
                client_options["aws_session_token"] = session_token
        self.client = client or boto3.client("ses", **client_options)
        self.CHARSET = charset
        self.from_address = from_address

    @staticmethod
    def _recipient_list(to_addresses):
        if isinstance(to_addresses, str):
            return [to_addresses]
        return list(to_addresses)

    def send_text_email(self, to_addresses, subject, content):
        return self.client.send_email(
            Destination={
                "ToAddresses": self._recipient_list(to_addresses),
            },
            Message={
                "Body": {
                    "Text": {
                        "Charset": self.CHARSET,
                        "Data": content,
                    }
                },
                "Subject": {
                    "Charset": self.CHARSET,
                    "Data": subject,
                },
            },
            Source=self.from_address,
        )

    def send_html_email(self, to_addresses, subject, content):
        return self.client.send_email(
            Destination={
                "ToAddresses": self._recipient_list(to_addresses),
            },
            Message={
                "Body": {
                    "Html": {
                        "Charset": self.CHARSET,
                        "Data": content,
                    }
                },
                "Subject": {
                    "Charset": self.CHARSET,
                    "Data": subject,
                },
            },
            Source=self.from_address,
        )

    def send_email(self, to_addresses, subject, text_content, html_content):
        """Send a multipart-style SES message with text and HTML alternatives."""
        return self.client.send_email(
            Destination={"ToAddresses": self._recipient_list(to_addresses)},
            Message={
                "Body": {
                    "Text": {"Charset": self.CHARSET, "Data": text_content},
                    "Html": {"Charset": self.CHARSET, "Data": html_content},
                },
                "Subject": {"Charset": self.CHARSET, "Data": subject},
            },
            Source=self.from_address,
        )
