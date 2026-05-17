FROM golang:1.23-alpine AS builder

WORKDIR /src
COPY go.mod ./
COPY . .
RUN go build -o /out/sandbox-service ./cmd/sandbox-service

FROM alpine:3.20

RUN apk add --no-cache python3
WORKDIR /app
COPY --from=builder /out/sandbox-service /app/sandbox-service

EXPOSE 8080
CMD ["/app/sandbox-service"]

