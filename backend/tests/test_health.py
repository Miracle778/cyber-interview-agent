async def test_health_contract(client):
    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "0.0.0",
        "checks": {
            "database": "skipped",
            "providers": "not_configured",
        },
    }
