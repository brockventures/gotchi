// Host tests for the pure SSE line parser (firmware/include/sse_parser.h).
// Run: cd firmware && pio test -e native
#include <unity.h>

#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "sse_parser.h"

#ifndef SSE_FIXTURE_PATH
#define SSE_FIXTURE_PATH "../tests/fixtures/sse_full_turn.txt"
#endif

using gotchi_sse::Event;
using gotchi_sse::Parser;

static std::vector<Event> feedAll(const std::vector<std::string>& chunks) {
    Parser p;
    std::vector<Event> out;
    auto collect = [&out](const Event& ev) { out.push_back(ev); };
    for (const auto& c : chunks) p.feed(c.data(), c.size(), collect);
    p.finish(collect);
    return out;
}

void test_one_event_split_across_three_feeds() {
    auto evs = feedAll({"eve", "nt: state\nda", "ta: {\"state\":\"idle\"}\n\n"});
    TEST_ASSERT_EQUAL_UINT(1, evs.size());
    TEST_ASSERT_EQUAL_STRING("state", evs[0].name.c_str());
    TEST_ASSERT_EQUAL_STRING("{\"state\":\"idle\"}", evs[0].data.c_str());
}

void test_crlf_line_endings() {
    auto evs = feedAll({"event: done\r\ndata: {\"duration_ms\":5}\r\n\r\n"});
    TEST_ASSERT_EQUAL_UINT(1, evs.size());
    TEST_ASSERT_EQUAL_STRING("done", evs[0].name.c_str());
    TEST_ASSERT_EQUAL_STRING("{\"duration_ms\":5}", evs[0].data.c_str());
}

void test_crlf_split_between_cr_and_lf() {
    auto evs = feedAll({"event: done\r", "\ndata: {}\r", "\n\r", "\n"});
    TEST_ASSERT_EQUAL_UINT(1, evs.size());
    TEST_ASSERT_EQUAL_STRING("done", evs[0].name.c_str());
    TEST_ASSERT_EQUAL_STRING("{}", evs[0].data.c_str());
}

void test_two_data_lines_joined_with_newline() {
    auto evs = feedAll({"event: x\ndata: first\ndata: second\n\n"});
    TEST_ASSERT_EQUAL_UINT(1, evs.size());
    TEST_ASSERT_EQUAL_STRING("first\nsecond", evs[0].data.c_str());
}

void test_unknown_fields_ignored() {
    auto evs = feedAll({"event: x\nid: 7\nretry: 100\n: keepalive comment\ndata: 1\n\n"});
    TEST_ASSERT_EQUAL_UINT(1, evs.size());
    TEST_ASSERT_EQUAL_STRING("x", evs[0].name.c_str());
    TEST_ASSERT_EQUAL_STRING("1", evs[0].data.c_str());
}

void test_blank_line_without_name_emits_nothing() {
    // Orphan data with no event name must not leak into the next named event.
    auto evs = feedAll({"data: orphan\n\nevent: y\ndata: 2\n\n"});
    TEST_ASSERT_EQUAL_UINT(1, evs.size());
    TEST_ASSERT_EQUAL_STRING("y", evs[0].name.c_str());
    TEST_ASSERT_EQUAL_STRING("2", evs[0].data.c_str());
}

void test_fixture_full_turn() {
    std::ifstream in(SSE_FIXTURE_PATH, std::ios::binary);
    TEST_ASSERT_TRUE_MESSAGE(in.good(), SSE_FIXTURE_PATH);
    std::stringstream ss;
    ss << in.rdbuf();
    std::string body = ss.str();

    auto evs = feedAll({body});
    std::vector<std::string> names;
    for (const auto& ev : evs) names.push_back(ev.name);

    const std::vector<std::string> expected = {
        "state", "state", "transcript", "status", "thinking", "reply",
        "state", "audio_chunk", "audio_chunk", "done"};
    TEST_ASSERT_EQUAL_UINT(expected.size(), names.size());
    for (size_t i = 0; i < expected.size(); ++i) {
        TEST_ASSERT_EQUAL_STRING(expected[i].c_str(), names[i].c_str());
    }
    TEST_ASSERT_TRUE(evs.back().data.find("duration_ms") != std::string::npos);
}

void setUp(void) {}
void tearDown(void) {}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_one_event_split_across_three_feeds);
    RUN_TEST(test_crlf_line_endings);
    RUN_TEST(test_crlf_split_between_cr_and_lf);
    RUN_TEST(test_two_data_lines_joined_with_newline);
    RUN_TEST(test_unknown_fields_ignored);
    RUN_TEST(test_blank_line_without_name_emits_nothing);
    RUN_TEST(test_fixture_full_turn);
    return UNITY_END();
}
