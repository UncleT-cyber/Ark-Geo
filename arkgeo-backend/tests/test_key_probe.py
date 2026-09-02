"""Provider key-probe + vision-ensemble contract tests.

These pin the REAL wire contracts for the geo-vision providers so a
regression in endpoint, header or payload shape fails loudly:

* GeoInfer — api.geoinfer.com, ``X-GeoInfer-Key`` header, multipart predict.
* GeoSpy   — dev.geospy.ai/predict, ``Bearer`` auth, ``geo_predictions`` body.
* Serper   — google.serper.dev/images, ``X-API-KEY`` header, JSON body.
"""
import httpx
import pytest
import respx

from app.brain.vision_ensemble import VisionEnsemble


# --------------------------------------------------------------------------- #
# GeoInfer probe
# --------------------------------------------------------------------------- #
class TestGeoinferProbe:
    @pytest.mark.asyncio
    async def test_probe_uses_models_endpoint_with_key_header(self):
        from app.services.key_probe import live_probe

        async with respx.mock() as mock:
            mock.get("https://api.geoinfer.com/v1/prediction/models").respond(
                200, json=[{"id": "global_v0_1", "type": "global", "enabled": True}]
            )
            res = await live_probe("geoinfer", "geo_pyw7test")
            req = mock.calls[0].request
            assert res["valid"] is True
            assert "GeoInfer" in res["detail"]
            assert req.headers["X-GeoInfer-Key"] == "geo_pyw7test"
            assert "Authorization" not in req.headers

    @pytest.mark.asyncio
    async def test_probe_rejects_bad_key(self):
        from app.services.key_probe import live_probe

        async with respx.mock() as mock:
            mock.get("https://api.geoinfer.com/v1/prediction/models").respond(401)
            res = await live_probe("geoinfer", "bad-key")
        assert res["valid"] is False
        assert "Unauthorized" in res["detail"]


# --------------------------------------------------------------------------- #
# GeoSpy probe
# --------------------------------------------------------------------------- #
class TestGeoSpyProbe:
    @pytest.mark.asyncio
    async def test_probe_accepts_auth_on_422_missing_image(self):
        """A 422 (body validation) only happens AFTER auth passes."""
        from app.services.key_probe import live_probe

        async with respx.mock() as mock:
            mock.post("https://dev.geospy.ai/predict").respond(422, json={})
            res = await live_probe("geospy", "real-key")
            req = mock.calls[0].request
            assert res["valid"] is True
            assert req.headers["Authorization"] == "Bearer real-key"

    @pytest.mark.asyncio
    async def test_probe_rejects_bad_key(self):
        from app.services.key_probe import live_probe

        async with respx.mock() as mock:
            mock.post("https://dev.geospy.ai/predict").respond(401)
            res = await live_probe("geospy", "sk-test")
        assert res["valid"] is False
        assert "Unauthorized" in res["detail"]


# --------------------------------------------------------------------------- #
# Serper probe — pins the documented endpoint/header contract
# --------------------------------------------------------------------------- #
class TestSerperProbe:
    @pytest.mark.asyncio
    async def test_probe_hits_images_endpoint_with_key_header(self):
        from app.services.key_probe import live_probe

        async with respx.mock() as mock:
            mock.post("https://google.serper.dev/images").respond(
                200, json={"images": []}
            )
            res = await live_probe("serper", "26aa53e3test")
            req = mock.calls[0].request
            assert res["valid"] is True
            assert req.headers["X-API-KEY"] == "26aa53e3test"
            assert b'"q"' in req.content

    @pytest.mark.asyncio
    async def test_probe_reports_key_rejected(self):
        from app.services.key_probe import live_probe

        async with respx.mock() as mock:
            mock.post("https://google.serper.dev/images").respond(403)
            res = await live_probe("serper", "bad")
        assert res["valid"] is False
        assert "HTTP 403" in res["detail"]


# --------------------------------------------------------------------------- #
# Vision-ensemble response parsing
# --------------------------------------------------------------------------- #
class TestGeoSpyParsing:
    @pytest.mark.asyncio
    async def test_parses_geo_predictions(self):
        body = {
            "geo_predictions": [
                {
                    "coordinates": [6.4588, 3.3830],
                    "score": 0.9,
                    "similarity_score_1km": 0.85,
                    "address": "Victoria Island, Lagos, Nigeria",
                }
            ]
        }
        ens = VisionEnsemble()
        async with httpx.AsyncClient() as client:
            with respx.mock() as mock:
                mock.post("https://dev.geospy.ai/predict").respond(200, json=body)
                res = await ens._query_geospy(client, "aGVsbG8=", "geo-key")
        assert res is not None
        assert res.source == "geospy"
        assert res.estimated_latitude == 6.4588
        assert res.estimated_longitude == 3.3830
        assert res.confidence_score == 0.85
        assert res.region == "Victoria Island, Lagos, Nigeria"

    @pytest.mark.asyncio
    async def test_empty_predictions_returns_none(self):
        ens = VisionEnsemble()
        async with httpx.AsyncClient() as client:
            with respx.mock() as mock:
                mock.post("https://dev.geospy.ai/predict").respond(
                    200, json={"geo_predictions": []}
                )
                res = await ens._query_geospy(client, "aGVsbG8=", "geo-key")
        assert res is None


class TestGeoInferParsing:
    @pytest.mark.asyncio
    async def test_parses_cluster_coordinates(self):
        body = {
            "data": {
                "prediction_id": "p1",
                "model_id": "global_v0_1",
                "credits_consumed": 1,
                "prediction": {
                    "result_type": "coordinates",
                    "clusters": [
                        {
                            "center": {"latitude": 6.4588, "longitude": 3.3830},
                            "location": {
                                "name": "Victoria Island",
                                "admin1": "Lagos State",
                                "admin2": "",
                                "country_code": "NG",
                            },
                            "radius_km": 5.0,
                            "points": [],
                        }
                    ],
                    "processing_time_ms": 400.0,
                },
            }
        }
        ens = VisionEnsemble()
        async with httpx.AsyncClient() as client:
            with respx.mock() as mock:
                route = mock.post("https://api.geoinfer.com/v1/prediction/predict").respond(
                    200, json=body
                )
                res = await ens._query_geoinfer(client, "aGVsbG8=", "geo_pyw7test")
        assert res is not None
        assert res.source == "geoinfer"
        assert res.estimated_latitude == 6.4588
        assert res.estimated_longitude == 3.3830
        assert res.search_radius_meters == 5000.0
        assert res.primary_country == "NG"
        assert res.region == "Lagos State"

        req = route.calls[0].request
        assert req.headers["X-GeoInfer-Key"] == "geo_pyw7test"
        assert b'name="file"' in req.content
        assert "model_id" not in str(req.url)

    @pytest.mark.asyncio
    async def test_pins_model_id_when_configured(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "geoinfer_model", "madrid_v2_0")
        body = {
            "data": {
                "prediction": {
                    "result_type": "accuracy",
                    "top_prediction": {
                        "latitude": 40.4168,
                        "longitude": -3.7038,
                        "confidence": 0.9,
                        "location": {
                            "name": "Madrid",
                            "admin1": "Community of Madrid",
                            "admin2": "",
                            "country_code": "ES",
                        },
                    },
                    "processing_time_ms": 200.0,
                }
            }
        }
        ens = VisionEnsemble()
        async with httpx.AsyncClient() as client:
            with respx.mock() as mock:
                route = mock.post("https://api.geoinfer.com/v1/prediction/predict").respond(
                    200, json=body
                )
                res = await ens._query_geoinfer(client, "aGVsbG8=", "geo_pyw7test")
        assert res is not None
        assert res.estimated_latitude == 40.4168
        assert "model_id=madrid_v2_0" in str(route.calls[0].request.url)

    @pytest.mark.asyncio
    async def test_parses_accuracy_top_prediction(self):
        body = {
            "data": {
                "prediction": {
                    "result_type": "accuracy",
                    "predictions": [],
                    "top_prediction": {
                        "latitude": 43.2630,
                        "longitude": -2.9350,
                        "confidence": 0.8,
                        "rank": 1,
                        "likely_pano_id": None,
                        "location": {
                            "name": "Bilbao",
                            "admin1": "Basque Country",
                            "admin2": "Biscay",
                            "country_code": "ES",
                        },
                    },
                    "processing_time_ms": 300.0,
                }
            }
        }
        ens = VisionEnsemble()
        async with httpx.AsyncClient() as client:
            with respx.mock() as mock:
                mock.post("https://api.geoinfer.com/v1/prediction/predict").respond(
                    200, json=body
                )
                res = await ens._query_geoinfer(client, "aGVsbG8=", "geo_pyw7test")
        assert res is not None
        assert res.estimated_latitude == 43.2630
        assert res.estimated_longitude == -2.9350
        assert res.confidence_score == 0.8
        assert res.primary_country == "ES"
        assert res.region == "Basque Country"

    @pytest.mark.asyncio
    async def test_empty_clusters_returns_none(self):
        body = {
            "data": {
                "prediction": {
                    "result_type": "coordinates",
                    "clusters": [],
                    "processing_time_ms": 300.0,
                }
            }
        }
        ens = VisionEnsemble()
        async with httpx.AsyncClient() as client:
            with respx.mock() as mock:
                mock.post("https://api.geoinfer.com/v1/prediction/predict").respond(
                    200, json=body
                )
                res = await ens._query_geoinfer(client, "aGVsbG8=", "geo_pyw7test")
        assert res is None
