# KnoRI — same tasks as ./run, for Linux/CI where make is available.
.DEFAULT_GOAL := help
.PHONY: help setup db down migrate api worker web up test test-fast web-test e2e lint fmt seed admin eval schema

help:      ; @./run help
setup:     ; @./run setup
db:        ; @./run db
down:      ; @./run down
migrate:   ; @./run migrate
api:       ; @./run api
worker:    ; @./run worker
web:       ; @./run web
up:        ; @./run up
test:      ; @./run test
test-fast: ; @./run test-fast
web-test:  ; @./run web-test
e2e:       ; @./run e2e
lint:      ; @./run lint
fmt:       ; @./run fmt
seed:      ; @./run seed $(PERSONA)
admin:     ; @./run admin $(EMAIL)
eval:      ; @./run eval
schema:    ; @./run schema
