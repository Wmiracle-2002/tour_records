package com.miracle.footmarks.data.remote

import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Test

class FootmarksApiTest {
    @Test
    fun defaultClientAllowsLongRunningAgentResponses() {
        val client = FootmarksApi.defaultClient()

        assertEquals(120_000, client.readTimeoutMillis)
        assertEquals(120_000, client.callTimeoutMillis)
    }

    @Test
    fun loginAndReadTripsMatchServerContract() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(
                MockResponse().setBody("""{"access_token":"access","refresh_token":"refresh","token_type":"bearer"}""")
                    .addHeader("Content-Type", "application/json")
            )
            server.enqueue(
                MockResponse().setBody(
                    """[{"id":8,"province_code":"110000","city_code":"110100","city_name":"北京市","start_date":"2026-09-01","end_date":"2026-09-03","created_at":"2026-09-01T10:00:00","records":[{"id":12,"trip_id":8,"type":"FOOD","name":"烤鸭","date":"2026-09-02","rating":null,"cost":"88.50","notes":null,"created_at":"2026-09-02T10:00:00"}]}]"""
                ).addHeader("Content-Type", "application/json")
            )
            server.start()
            val api = FootmarksApi.create(server.url("/").toString())

            val tokens = api.login(LoginRequest("shared", "password"))
            val trips = api.getTrips("Bearer ${tokens.accessToken}")

            assertEquals("POST", server.takeRequest().method)
            val request = server.takeRequest()
            assertEquals("/api/v1/trips", request.path)
            assertEquals("Bearer access", request.getHeader("Authorization"))
            assertEquals("110100", trips.single().cityCode)
            assertEquals("88.50", trips.single().records.single().cost)
        }
    }

    @Test
    fun writesUseAuthenticatedTripAndRecordEndpoints() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setResponseCode(201).setBody("""{"id":8,"province_code":"110000","city_code":"110100","city_name":"北京市","start_date":"2026-09-01","end_date":"2026-09-03","created_at":"2026-09-01T10:00:00"}""").addHeader("Content-Type", "application/json"))
            server.enqueue(MockResponse().setResponseCode(201).setBody("""{"id":12,"trip_id":8,"type":"FOOD","name":"烤鸭","date":"2026-09-02","rating":null,"cost":"88.50","notes":null,"created_at":"2026-09-02T10:00:00"}""").addHeader("Content-Type", "application/json"))
            server.enqueue(MockResponse().setResponseCode(204))
            server.start()
            val api = FootmarksApi.create(server.url("/").toString())

            val trip = api.createTrip("Bearer token", TripRequest("110000", "110100", "北京市", "2026-09-01", "2026-09-03"))
            val record = api.createRecord("Bearer token", trip.id, RecordRequest("FOOD", "烤鸭", "2026-09-02", null, "88.50", null))
            api.deleteRecord("Bearer token", record.id)

            assertEquals("/api/v1/trips", server.takeRequest().path)
            val create = server.takeRequest()
            assertEquals("/api/v1/trips/8/records", create.path)
            assertEquals("Bearer token", create.getHeader("Authorization"))
            assertEquals("/api/v1/records/12", server.takeRequest().path)
        }
    }

    @Test
    fun sessionRefreshesExpiredAccessBeforeReadingTrips() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setBody("""{"access_token":"old","refresh_token":"refresh","token_type":"bearer"}""").addHeader("Content-Type", "application/json"))
            server.enqueue(MockResponse().setResponseCode(401))
            server.enqueue(MockResponse().setBody("""{"access_token":"new","refresh_token":"new-refresh","token_type":"bearer"}""").addHeader("Content-Type", "application/json"))
            server.enqueue(MockResponse().setBody("[]").addHeader("Content-Type", "application/json"))
            server.start()
            val session = CloudSession(FootmarksApi.create(server.url("/").toString()), MemoryTokenStore())

            session.login("shared", "password")
            assertEquals(emptyList<RemoteTrip>(), session.getTrips())
            server.takeRequest()
            assertEquals("Bearer old", server.takeRequest().getHeader("Authorization"))
            assertEquals("/api/v1/auth/refresh", server.takeRequest().path)
            assertEquals("Bearer new", server.takeRequest().getHeader("Authorization"))
        }
    }

    @Test
    fun movingSingleDayRecordSendsTripAndRecordInOneRequest() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setBody("""{"id":12,"trip_id":8,"type":"FOOD","name":"烤鸭","date":"2026-09-05","rating":null,"cost":null,"notes":null}""").addHeader("Content-Type", "application/json"))
            server.start()
            val api = FootmarksApi.create(server.url("/").toString())
            api.updateRecord(
                "Bearer access", 12,
                RecordRequest("FOOD", "烤鸭", "2026-09-05", null, null, null,
                    TripRequest("110000", "110100", "北京市", "2026-09-05", "2026-09-05"))
            )
            val request = server.takeRequest()
            assertEquals("PATCH", request.method)
            assertEquals("/api/v1/records/12", request.path)
            org.junit.Assert.assertTrue(request.body.readUtf8().contains("\"start_date\":\"2026-09-05\""))
        }
    }

    @Test
    fun agentChatUsesAuthenticatedEndpointAndParsesResponse() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(
                MockResponse()
                    .setBody("""{"request_id":"req-1","answer":"行程结果"}""")
                    .addHeader("Content-Type", "application/json")
            )
            server.start()
            val api = FootmarksApi.create(server.url("/").toString())

            val response = api.chat(
                "Bearer access",
                AgentChatRequest("北京三日游")
            )

            val request = server.takeRequest()
            assertEquals("POST", request.method)
            assertEquals("/api/v1/agent/chat", request.path)
            assertEquals("Bearer access", request.getHeader("Authorization"))
            assertEquals("{\"message\":\"北京三日游\"}", request.body.readUtf8())
            assertEquals("req-1", response.requestId)
            assertEquals("行程结果", response.answer)
        }
    }

    @Test
    fun agentChatRefreshesExpiredAccessTokenOnce() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setResponseCode(401))
            server.enqueue(
                MockResponse()
                    .setBody("""{"access_token":"new-access","refresh_token":"new-refresh","token_type":"bearer"}""")
                    .addHeader("Content-Type", "application/json")
            )
            server.enqueue(
                MockResponse()
                    .setBody("""{"request_id":"req-2","answer":"规划完成"}""")
                    .addHeader("Content-Type", "application/json")
            )
            server.start()
            val store = MemoryTokenStore().apply {
                tokens = Tokens("old-access", "refresh")
            }
            val session = CloudSession(FootmarksApi.create(server.url("/").toString()), store)

            val response = session.askAgent("北京三日游")

            val expiredRequest = server.takeRequest()
            val refreshRequest = server.takeRequest()
            val retriedRequest = server.takeRequest()
            assertEquals("/api/v1/agent/chat", expiredRequest.path)
            assertEquals("Bearer old-access", expiredRequest.getHeader("Authorization"))
            assertEquals("/api/v1/auth/refresh", refreshRequest.path)
            assertEquals("Bearer new-access", retriedRequest.getHeader("Authorization"))
            assertEquals("req-2", response.requestId)
            assertEquals("new-refresh", store.tokens?.refreshToken)
        }
    }

    private class MemoryTokenStore : TokenStore {
        override var tokens: Tokens? = null
    }
}
