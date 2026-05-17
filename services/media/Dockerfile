FROM golang:1.23-alpine AS builder

WORKDIR /src
COPY go.mod ./
COPY . .
RUN go build -o /out/media-service ./cmd/media-service

FROM alpine:3.20

WORKDIR /app
COPY --from=builder /out/media-service /app/media-service

EXPOSE 8080
CMD ["/app/media-service"]

