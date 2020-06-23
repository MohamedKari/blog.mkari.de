pub:
	./publish.sh

go-live:
	git push origin gh-pages

hugo-serve:
	hugo serve -D

web-serve:
	cd public && http-server
