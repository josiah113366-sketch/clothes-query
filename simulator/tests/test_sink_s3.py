import inspect

from botocore.exceptions import ClientError, NoCredentialsError

from sim.sink import s3


def _client_error(code: str) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": "arn:aws:s3:::secret-bucket-name"}}, "Op"
    )


def test_errors_are_classified_without_raw_message() -> None:
    assert "권한" in s3.describe_error(_client_error("AccessDenied"))
    assert "버킷이 없습니다" in s3.describe_error(_client_error("NoSuchBucket"))
    assert "리전" in s3.describe_error(_client_error("PermanentRedirect"))
    assert "자격 증명" in s3.describe_error(NoCredentialsError())
    for code in ("AccessDenied", "NoSuchBucket", "Weird"):
        assert "secret-bucket-name" not in s3.describe_error(_client_error(code))


def test_reader_has_no_write_or_delete_methods() -> None:
    names = {n for n, _ in inspect.getmembers(s3.S3Reader, inspect.isfunction)}
    assert not {
        n for n in names if any(w in n for w in ("put", "delete", "upload", "write", "remove"))
    }
    source = inspect.getsource(s3)
    for forbidden in ("put_object", "delete_object", "upload_file", "delete_objects"):
        assert forbidden not in source


def test_check_access_reports_reason_only() -> None:
    class Denied:
        def list_objects_v2(self, **_: object) -> None:
            raise _client_error("AccessDenied")

    reader = s3.S3Reader("some-bucket", "ap-northeast-1", client=Denied())
    try:
        reader.check_access()
    except s3.S3Error as error:
        assert "권한" in str(error) and "some-bucket" not in str(error)
    else:
        raise AssertionError("S3Error가 나야 한다")
